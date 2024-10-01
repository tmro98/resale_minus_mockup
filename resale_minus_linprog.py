class IntercompanyTransaction:
    def __init__(self, intercompany_invoice_number, end_customer_invoice_number, selling_company_id, buying_company_id, transferred_goods):
        
        self.intercompany_invoice_number = intercompany_invoice_number
        self.end_customer_invoice_number = end_customer_invoice_number
        self.selling_company_id = selling_company_id
        self.buying_company_id = buying_company_id
        self.transferred_goods = transferred_goods  # Dictionary {material_number: quantity}

    def segmentation(self, verbose=False):
        divs = []
        for good in self.transferred_goods:
            divs.append(get_datapoint("material_master",good ,"division"))
        if divs.count("sd") > divs.count("md"):
            setattr(self, "segment", "sd")
        else:
            setattr(self, "segment", "md")

        if verbose:
            print(divs)


class EndCustomerInvoice:
    def __init__(self, invoice_number, relative_ic_invoice_number, company_id, end_customer_name, sold_products, other_cogs, funcexp_ratio):
       
        self.invoice_number = invoice_number
        self.relative_ic_invoice_number = relative_ic_invoice_number
        self.company_id = company_id
        self.end_customer_name = end_customer_name
        self.sold_products = sold_products  # Dictionary {material_number: {quantity: int, price_per_unit: float}}
        self.other_cogs = other_cogs 
        self.funcexp_ratio = funcexp_ratio  

    def get_material_net_sales_value(self, material_number):

        if material_number in self.sold_products:
            product_info = self.sold_products[material_number]
            quantity = product_info['quantity']
            price_per_unit = product_info['price_per_unit']
            material_net_sales = quantity * price_per_unit
            
            return material_net_sales
        
    def calc_total_net_sales(self):

        total_net_sales = 0

        for prod in self.sold_products:
            total_net_sales += (self.sold_products[prod]["quantity"] * self.sold_products[prod]["price_per_unit"])
        
        setattr(self, "total_net_sales",total_net_sales)
        return total_net_sales
    

class Estimate_EndCustomerInvoice:
    def __init__(self, intercompany_invoice, other_cogs_ratio, funcexp_ratio):
    
        self.invoice_number = None
        self.relative_ic_invoice_number = None
        self.company_id = intercompany_invoice.buying_company_id
        self.end_customer_name = None
        # Dictionary {material_number: {quantity: int, price_per_unit: float}}
        self.sold_products = {mat:{"quantity":intercompany_invoice.transferred_goods[mat], "price_per_unit":get_datapoint("SMART", mat, self.company_id+"_avgsp")} 
                                    for mat in intercompany_invoice.transferred_goods}
 
        self.funcexp_ratio = funcexp_ratio 
        self.other_cogs_ratio = other_cogs_ratio 
            
    def calc_total_net_sales(self):

        total_net_sales = 0

        for prod in self.sold_products:
            total_net_sales += (self.sold_products[prod]["quantity"] * self.sold_products[prod]["price_per_unit"])
            
        setattr(self, "total_net_sales",total_net_sales)
        setattr(self, "other_cogs", round(total_net_sales*self.other_cogs_ratio,2))
        return total_net_sales
    
class RminusEngine:

    prev_calc_tp_collector = {"001":{}, "002":{}}
    ini_tp = {"001":{}, "002":{}}
    counter = {"001":0, "002":0}

    def __init__(self, intercompany_transaction, end_customer_invoice=None, est_cogs_ratio = 0.09, est_func_exp = 0.15):
        
        self.intercompany_transaction = intercompany_transaction

        if end_customer_invoice is not None:
            self.end_customer_invoice = end_customer_invoice
        else:
            self.end_customer_invoice = Estimate_EndCustomerInvoice(intercompany_invoice=self.intercompany_transaction,
                                                                     other_cogs_ratio=est_cogs_ratio, 
                                                                     funcexp_ratio=est_func_exp)

    def calc_target_transfer_cost(self, verbose=False):
        
        self.intercompany_transaction.segmentation()
        self.end_customer_invoice.calc_total_net_sales()

        seg = self.intercompany_transaction.segment

        target_margin = get_datapoint("target_margin", 
                        self.end_customer_invoice.company_id + "_" + seg, "target")
        total_net_sales = self.end_customer_invoice.total_net_sales
        other_costs = self.end_customer_invoice.other_cogs + total_net_sales*self.end_customer_invoice.funcexp_ratio

        target_profit = target_margin*total_net_sales
        target_transfer_costs = total_net_sales - other_costs - target_profit

        calc_margin = (total_net_sales - target_transfer_costs - other_costs)/total_net_sales

        if verbose:
            print("divison", seg)
            print("target margin", target_margin)
            print("target_transfer_costs", round(target_transfer_costs, 2))
            print("calculated_margin", round(calc_margin,3))
    
        setattr(self, "target_transfer_costs", round(target_transfer_costs, 2))
        return round(target_transfer_costs, 2)
    
    def calc_target_cm(self, target_cm=0.05, verbose=False):
        
        self.end_customer_invoice.calc_total_net_sales()
 
        total_net_sales = self.end_customer_invoice.total_net_sales
        direct_costs = self.end_customer_invoice.other_cogs 

        target_profit_cm = target_cm*total_net_sales
        target_costs_cm = total_net_sales - direct_costs - target_profit_cm

        if verbose:
            calc_cm = (total_net_sales - target_costs_cm - direct_costs)/total_net_sales
            print("calculated cm: ", calc_cm)

        setattr(self, "target_costs_cm", target_costs_cm)
        return round(target_costs_cm, 2)
    

    def calc_old_transfer_prices(self):
        ini_transfer_prices = {}

        if RminusEngine.counter[self.intercompany_transaction.buying_company_id] == 0:

            for mat in self.intercompany_transaction.transferred_goods:
                zref = get_datapoint("material_master", mat, "zref")
                pg = get_datapoint("material_master", mat, "product_group"),
                td = get_datapoint("td_matrix_sd", pg, self.intercompany_transaction.buying_company_id)

                ini_transfer_prices[mat] = round(zref - (zref * td/100), 2)

            RminusEngine.ini_tp[self.intercompany_transaction.buying_company_id] = ini_transfer_prices

            for mat in self.intercompany_transaction.transferred_goods:
                    RminusEngine.prev_calc_tp_collector[self.intercompany_transaction.buying_company_id][mat] = ini_transfer_prices[mat]

        return 1
    
    def optimize(self, manu_margin=0.05):

        coeffs = np.zeros(1 + len(self.end_customer_invoice.sold_products))

        coeffs[0] = self.target_transfer_costs
        for num, product in enumerate(self.end_customer_invoice.sold_products):
            coeffs[num+1] = self.end_customer_invoice.sold_products[product]["quantity"] * -1
        
        price_ub = coeffs * -1
        price_ub[0] = 0

        prod_costs_ub = np.zeros((len(coeffs)-1,len(coeffs)))
        for i in range(len(coeffs)-1):
            prod_costs_ub[i,i+1] = -1

        A_ub = np.vstack((price_ub, prod_costs_ub))

        b_ub = np.zeros(len(coeffs))
        b_ub[0] = np.min([self.target_transfer_costs, self.target_costs_cm])

        for num, product in enumerate(self.end_customer_invoice.sold_products):
            b_ub[num+1] = get_datapoint("material_master", product, "prod_costs")*-(1+manu_margin)

        A_eq = np.zeros((1, (len(coeffs))))
        A_eq[0,0] = 1

        b_eq = np.array([1])

        x0_bounds = [(1,1)]

        customs_restrictions = {}

        for prod in self.intercompany_transaction.transferred_goods:
                customs_restrictions[prod] = (RminusEngine.prev_calc_tp_collector[self.intercompany_transaction.buying_company_id][prod]
                                              *(1-get_datapoint("customs_restrictions", self.intercompany_transaction.buying_company_id, "max_tp_decrease_%")),
                                             RminusEngine.prev_calc_tp_collector[self.intercompany_transaction.buying_company_id][prod]*
                                             (1+get_datapoint("customs_restrictions", self.intercompany_transaction.buying_company_id, "max_tp_increase_%")))


        tp_bounds = [
                    (max(get_datapoint("material_master", product, "zref")*0.2, customs_restrictions[product][0]),
                    min(get_datapoint("material_master", product, "zref")*0.9,customs_restrictions[product][1]))
                    for product in self.intercompany_transaction.transferred_goods
                    ]
        
        lb_cost = 0
        ub_cost = 0

        for num, product in enumerate(self.end_customer_invoice.sold_products):
            lb_cost += self.end_customer_invoice.sold_products[product]["quantity"] * tp_bounds[num][0]
            ub_cost += self.end_customer_invoice.sold_products[product]["quantity"] * tp_bounds[num][1]

        new_discounts = {}
        new_transfer_prices = {}

        if self.target_transfer_costs < lb_cost:

            print("target tp cost < lower cost bound, using lowest possible prices")

            for num, mat in enumerate(self.intercompany_transaction.transferred_goods):
                zref = get_datapoint("material_master", mat, "zref")
                new_discounts[mat] = np.round(1 - tp_bounds[num][0]/zref,2)
                new_transfer_prices[mat] = np.round(tp_bounds[num][0],2)

                setattr(self, "summary", 
                        {"calc_transfer_prices":new_transfer_prices, 
                        "calc_transfer_discounts":new_discounts})
                
            calc_tp_cost = lb_cost

        elif self.target_transfer_costs > ub_cost:

            print("target tp cost > upper cost bound, using highest possible prices")

            for num, mat in enumerate(self.intercompany_transaction.transferred_goods):
                zref = get_datapoint("material_master", mat, "zref")
                new_discounts[mat] = np.round(1 - tp_bounds[num][1]/zref,2)
                new_transfer_prices[mat] = np.round(tp_bounds[num][1],2)

                setattr(self, "summary", 
                        {"calc_transfer_prices":new_transfer_prices, 
                        "calc_transfer_discounts":new_discounts})
                
            calc_tp_cost = ub_cost

        else:

            bounds = x0_bounds + tp_bounds

            result = linprog(c=coeffs, 
                            A_ub=A_ub, 
                            b_ub=b_ub, 
                            A_eq=A_eq, 
                            b_eq=b_eq, 
                            bounds=bounds, 
                            method="highs")
            
            for num, mat in enumerate(self.intercompany_transaction.transferred_goods):
                zref = get_datapoint("material_master", mat, "zref")
                new_discounts[mat] = np.round(1 - result.x[num+1]/zref,2)
                new_transfer_prices[mat] = np.round(result.x[num+1],2)
            
            calc_tp_cost =  np.round(np.dot(result.x[1:], A_ub[0,:][1:]), 2)

            setattr(self, "optimization_message", result.message)
            
        try:

            absolute_margin = (self.end_customer_invoice.total_net_sales
                                -calc_tp_cost
                                -(self.end_customer_invoice.other_cogs 
                                + self.end_customer_invoice.total_net_sales
                                *self.end_customer_invoice.funcexp_ratio))
            
            final_margin_check = absolute_margin/self.end_customer_invoice.total_net_sales
                
            old_transfer_costs = 0
                
            if (get_datapoint("customs_restrictions", self.intercompany_transaction.buying_company_id, "max_tp_increase_%") +
                get_datapoint("customs_restrictions", self.intercompany_transaction.buying_company_id, "max_tp_decrease_%")) < 1000:
                for prod in self.end_customer_invoice.sold_products:
                    old_transfer_costs += (self.end_customer_invoice.sold_products[prod]["quantity"] * RminusEngine.prev_calc_tp_collector[self.intercompany_transaction.buying_company_id][prod])
            
            else: 
                for prod in self.end_customer_invoice.sold_products:
                    old_transfer_costs += (self.end_customer_invoice.sold_products[prod]["quantity"] * RminusEngine.ini_tp[self.intercompany_transaction.buying_company_id][prod])

            absolute_margin_old = (self.end_customer_invoice.total_net_sales
                                    -old_transfer_costs
                                    -(self.end_customer_invoice.other_cogs 
                                    + self.end_customer_invoice.total_net_sales
                                    *self.end_customer_invoice.funcexp_ratio))

            old_margin_check = absolute_margin_old/self.end_customer_invoice.total_net_sales


            setattr(self, "summary", 
                        {"total_net_sales":self.end_customer_invoice.total_net_sales,
                        "calc_transfer_prices":new_transfer_prices, 
                        "calc_transfer_discounts":new_discounts,
                        "total_transfer_costs":calc_tp_cost,
                        "old_transfer_costs":np.round(old_transfer_costs,2),
                        "other_costs":(self.end_customer_invoice.other_cogs 
                                      + self.end_customer_invoice.total_net_sales
                                      *self.end_customer_invoice.funcexp_ratio),
                        "absolute_margin":np.round(absolute_margin,2),
                        "absolute_margin_old":np.round(absolute_margin_old,2),
                        "calc_margin_check":np.round(final_margin_check,3),
                        "old_margin_check":np.round(old_margin_check,3)})

            for mat in new_transfer_prices:
                RminusEngine.prev_calc_tp_collector[self.intercompany_transaction.buying_company_id][mat] = new_transfer_prices[mat]

                RminusEngine.counter[self.intercompany_transaction.buying_company_id] += 1
                
            return 1
            
        except:
                
            print("something else went wrong")
        
    def run(self, target_cm=0.05, manu_margin=0.05):
        self.calc_target_transfer_cost()
        self.calc_old_transfer_prices()
        self.calc_target_cm(target_cm)
        self.optimize(manu_margin)

        return 1