"""
Business Case / Capital Project Model – EZ Sensor Pro 2.4GHz portfolio (3 products)
Structure mirrors the company Excel ("Cashflow_specific_idea_v3.xlsx"):
  Net Revenue -> OTP unit cost (Material + CLAM + Freight + FG duties) -> COGS -> Gross (Make) Margin
  -> RD&E, SG&A, Cost of payment terms -> Contribution Margin -> Free Cash Flow -> NPV / IRR / Payback

Products (unit costs from the Sensata Item Readiness Report, 27-Sep-2026):
  90518125507  HSSI EU (10°)  -> sold in Europe only
  90518125519  HSSI NA (20°)  -> sold in the USA only
  90518125533  Gamma NA/EU    -> sold in the USA and Europe

All money is in $k (thousands of USD). Volumes are in k units, unit prices/costs in $/unit,
so k units x $/unit = $k.
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go


st.set_page_config(page_title="Business Case Model", layout="wide")


# =====================================================
# CONSTANTS
# =====================================================

# Default volume forecast (k units, all 3 products together) from launch year onwards
DEFAULT_VOLUME_FORECAST = [4.5, 237.9, 434.7, 959.3, 1403.1, 1755.0]

# From sheet "Payments terms": contracted payment days -> cost as % of item net revenue
PAYMENT_TERMS_TABLE = {
    30: 0.0, 45: 0.5, 60: 1.0, 75: 1.5, 90: 2.0, 120: 3.0, 150: 4.0,
    180: 5.0, 210: 6.0, 240: 7.0, 270: 8.0, 300: 9.0, 330: 10.0, 360: 11.0,
}


# =====================================================
# PRODUCT DATA – Item Readiness Report (Bill of Materials -> Pending costs)
# =====================================================

ELEMENTS = ["MAT", "TL_MOH", "PL_MOH", "TL_RES", "PL_RES", "TL_OH", "PL_OH", "OP"]


def _c(MAT, PL_MOH, TL_RES, TL_OH, TOTAL, TL_MOH=0.0, PL_RES=0.0, PL_OH=0.0, OP=0.0):
    return dict(MAT=MAT, TL_MOH=TL_MOH, PL_MOH=PL_MOH, TL_RES=TL_RES, PL_RES=PL_RES,
                TL_OH=TL_OH, PL_OH=PL_OH, OP=OP, TOTAL_REPORTED=TOTAL)


# Make site: AGM (Mexico). Values = Item Readiness Report, AGM organisation.
PRODUCTS = {
    "HSSI_EU": dict(pn="90518125507", name="HSSI EU (10°)", weight_g=36.0, markets="Europe only",
                    costs={"Pending": _c(4.66664, 0.24960, 0.14705, 0.34695, 5.41024)}),
    "HSSI_NA": dict(pn="90518125519", name="HSSI NA (20°)", weight_g=36.0, markets="USA only",
                    costs={"Pending": _c(4.43486, 0.23721, 0.14705, 0.34695, 5.16607)}),
    "GAMMA": dict(pn="90518125533", name="Gamma NA/EU", weight_g=54.0, markets="USA + Europe",
                  costs={"Pending": _c(5.26008, 0.28134, 1.51820, 3.38990, 10.44952)}),
}
PKEYS = list(PRODUCTS.keys())
PNAME = {pk: PRODUCTS[pk]["name"] for pk in PKEYS}
SHARE_COL = {"HSSI_EU": "HSSI EU %", "HSSI_NA": "HSSI NA %", "GAMMA": "Gamma %"}
MAKE_SITE = "AGM (Mexico)"
MARKETS = {"US": "USA", "EU": "Europe"}
LANES = [("MX", "US"), ("MX", "EU")]
ROUTE_DC = "Via Sensata DC – intercompany invoice"
ROUTE_DIRECT = "Direct to customer – invoice at selling price"
ROUTE_NAME = {"dc": "via Sensata DC", "direct": "direct to customer"}

# Incoterms 2020 – what the SELLER (Sensata) pays on the leg to the customer
INCOTERMS = {
    "EXW – Ex Works": dict(freight=False, insurance=False, duty=False, sea=False,
                           desc="Buyer collects the goods at the seller's site and pays all transport, export and import clearance and duty."),
    "FCA – Free Carrier": dict(freight=False, insurance=False, duty=False, sea=False,
                               desc="Seller clears export and hands the goods to the buyer's carrier; buyer pays main transport, import clearance and duty."),
    "FAS – Free Alongside Ship": dict(freight=False, insurance=False, duty=False, sea=True,
                                      desc="Sea only. Seller delivers alongside the ship at the port of shipment; buyer pays main transport and duty."),
    "FOB – Free On Board": dict(freight=False, insurance=False, duty=False, sea=True,
                                desc="Sea only. Seller loads the goods on board at the port of shipment; buyer pays main transport and duty."),
    "CPT – Carriage Paid To": dict(freight=True, insurance=False, duty=False, sea=False,
                                   desc="Seller pays main transport to the named place; risk passes at hand-over to the first carrier; buyer pays duty."),
    "CIP – Carriage and Insurance Paid To": dict(freight=True, insurance=True, duty=False, sea=False,
                                                 desc="Like CPT, plus the seller buys cargo insurance; buyer pays duty."),
    "CFR – Cost and Freight": dict(freight=True, insurance=False, duty=False, sea=True,
                                   desc="Sea only. Seller pays sea freight to the port of destination; buyer pays duty."),
    "CIF – Cost, Insurance and Freight": dict(freight=True, insurance=True, duty=False, sea=True,
                                              desc="Sea only. Like CFR, plus the seller buys cargo insurance; buyer pays duty."),
    "DAP – Delivered At Place": dict(freight=True, insurance=False, duty=False, sea=False,
                                     desc="Seller delivers to the named place, ready for unloading; buyer pays import clearance and duty."),
    "DPU – Delivered at Place Unloaded": dict(freight=True, insurance=False, duty=False, sea=False,
                                              desc="Like DAP, but the seller also unloads; buyer pays import clearance and duty."),
    "DDP – Delivered Duty Paid": dict(freight=True, insurance=False, duty=True, sea=False,
                                      desc="Seller delivers to the named place and pays import clearance and duty."),
}
TERM_LIST = list(INCOTERMS)
DEFAULT_TERM = {"dc": "DAP – Delivered At Place", "direct": "DDP – Delivered Duty Paid"}
COMBINED = "Combined (3 products)"
VIEWS = [COMBINED] + [PNAME[pk] for pk in PKEYS]
VIEW_KEY = {PNAME[pk]: pk for pk in PKEYS}


def el(cd, keys):
    return sum(cd[k] for k in keys)


def std_split(cd):
    """Cost elements -> model building blocks ($/unit)."""
    return dict(mat=cd["MAT"], moh=el(cd, ["TL_MOH", "PL_MOH"]), dl=el(cd, ["TL_RES", "PL_RES"]),
                oh=el(cd, ["TL_OH", "PL_OH", "OP"]))


def std_total(cd):
    return el(cd, ELEMENTS)


def std_conv(cd):
    return el(cd, ["TL_RES", "PL_RES", "TL_OH", "PL_OH", "OP"])


def std_steps(cd):
    return " + ".join(f"{k} {cd[k]:.5f}" for k in ELEMENTS if cd[k] != 0) + f" = **{std_total(cd):.5f}**"


# =====================================================
# IN-APP GUIDE (legend per tab)
# =====================================================

GUIDE_TITLES = {"overview": "ℹ️ How this model works", "tab": "ℹ️ How to read this tab"}

GUIDE = {
    "overview": """
**What this model does.** It evaluates the EZ Sensor Pro project (3 products) the same way the company business-case Excel does, and shows whether it is worth investing in – for the three products together and for each one separately.

**How the numbers flow**
1. **Net revenue** = volume × selling price (ASP), plus samples, CUF and quicksavings.
2. **Unit cost (OTP)** = material (incl. material overhead) + CLAM (make-site conversion cost) + freight to the market + finished-goods duties.
3. **Gross (make) margin** = net revenue − all cost of goods sold.
4. **Contribution margin** = gross margin − RD&E − SG&A − cost of payment terms.
5. **Free cash flow** = the real cash the project brings in or uses each year.
6. **NPV, IRR and payback** turn the cash flows into a go / no-go answer.

**Three products.** The volume table in the sidebar is the total for all three products, with the split per product per year next to it. Unit costs are pre-filled with the standard costs from the Item Readiness Report of each product for the make site **AGM (Mexico)** and can be edited by hand in the sidebar. The **view selector** at the top switches every tab between the combined case and one product.

**Units.** All money is in **$k** (thousands of USD). Volumes are in **k units**: 4.5 = 4,500 units.

**How to use it.** Set the assumptions in the sidebar on the left; hover the ⓘ icons for definitions. Every tab updates immediately and ends with **Takeaways**: what the numbers say and what to do about it. The last tab collects all of them.
""",
    "summary": """
The one-page answer: is the project worth doing?

**Top row**
- **Total net revenue** – all revenue over the project horizon.
- **NPV (Net Present Value)** – all future cash flows converted to today's money and added up. Above 0 means the project earns more than the required return (WACC).
- **IRR** – the yearly return the project delivers. It must be higher than the WACC.
- **Payback** – years until the cumulative cash turns positive, counted from the project start.
- **Avg contribution margin** – total contribution margin ÷ total net revenue.

**Second row**
- **ROI** – total free cash flow ÷ total investment (CapEx + net RD&E + quicksavings paid).
- **Return on RD&E** – EBIT of the first 5 project years per $1 of program-specific RD&E (as in the company Excel).
- **Discounted payback** – like payback, but on discounted cash; always a bit longer.
- **Avg gross (make) margin** – margin after all product costs, before RD&E and SG&A.

**Why discount?** $1 today is worth more than $1 later: you could invest it, and the future is uncertain. At a 12% WACC, $1,000 received in 1 year is worth about $893 today, in 5 years about $567, in 10 years about $322. The **WACC / discount rate** (sidebar → Investment decision) is the minimum yearly return the company requires. A higher rate gives a lower NPV.

**Investment decision** – the same table as in the company Excel. The hurdle rates are set in the sidebar (Investment decision); the values come from this model.
- **NPV** at the WACC must be above $0.
- **Manufacturing margin** = gross (make) margin ÷ net revenue over the horizon. It must beat each benchmark: Tire Management Solutions, TPMS and Sensata worldwide.
- **Payback** must be shorter than the hurdle (years from the project start).
- **Explanation** – 🟢 hurdle met, 🔴 not met, ⚪ no hurdle.
- **Accretion / (dilution), year with highest revenue** = (manufacturing margin of that year − benchmark) × net revenue of that year, in $k. Positive: the project raises the benchmark's margin; in brackets: it dilutes it.
- **NPD Effectiveness** = net revenue of years 1–5 ÷ program-specific RD&E (total over the project).
- **Return on RD&E** = EBIT of years 1–5 ÷ program-specific RD&E (total). EBIT = contribution margin in this model.
- Years 1–5 are the first five years of the project, counted from the project start (pre-launch years included).
""",
    "products": """
Where the unit costs come from. The cost table in the sidebar is **pre-filled** with the standard costs from the **Item Readiness Report** (Bill of Materials → Pending costs) of each product for the make site **AGM (Mexico)**. **Every value can be edited by hand**; edited values are marked, and *Reset to standard costs* restores the report values. *Clear table* lets you enter everything manually.

**Cost elements and where they go in the model**
- **MAT** – material, the cost of the purchased parts → *Material*.
- **MOH** – material overhead: duty and freight of the components to Sensata → *Material overhead (MOH)*. It is the difference between the "Parts cost" and "Material cost" sheets.
- **RES** – resources, direct labour → *Direct labour*.
- **OH** – other overhead (indirect labour, etc.) → *Indirect labour & overhead*.
- **TL / PL** – This Level (cost added at this level) / Prior Levels (sum of all prior levels).

**Pending cost.** The model uses the pending cost only: it is updated every quarter and is the latest view of the unit cost.

**Conversion cost = RES + OH** is what the plant adds on top of the material. Comparing it between products in the same plant shows which process is mature and which is still in ramp-up.

**Landed cost** = pending cost + freight to the market + finished-goods duty.
""",
    "tariffs": """
Duties on the **finished product** when it crosses a border to the market. Duties on components are already in MOH.

**Lanes.** All products are made in AGM (Mexico): HSSI EU → Europe, HSSI NA → USA, Gamma → both (split in the sidebar).

**How the duty is calculated.** Duty per unit = duty rate × customs value. The customs value is the price on the invoice with which the goods are imported, so it depends on the **sales route** (sidebar, separately for the USA and Europe):
- **Via Sensata DC – intercompany invoice.** AGM invoices the Sensata distribution centre (Fort Worth / Bergkirchen), which then sells to the customer. Customs value = make-site cost × (1 + intercompany mark-up). The EU adds the freight to the EU border (CIF basis); the USA does not (FOB basis). The mark-up must be at arm's length and is set by Sensata Tax.
- **Direct to customer – invoice at selling price.** AGM invoices the customer directly. Customs value = the selling price (ASP), which is higher, so the duty is higher.

If the product qualifies for a preferential origin (**USMCA** for Mexico → USA, the EU–Mexico agreement for Mexico → Europe) the rate is 0%.

**Freight terms (Incoterms 2020).** They decide which costs Sensata carries on the leg to the customer:
- **E / F terms (EXW, FCA, FAS, FOB)** – the customer pays the main transport and the import duty.
- **C terms (CPT, CIP, CFR, CIF)** – Sensata pays the main transport (CIP / CIF also the cargo insurance); the customer pays the duty.
- **D terms (DAP, DPU)** – Sensata pays the transport to the named place; the customer pays the duty.
- **DDP** – Sensata pays everything, including the import duty.

*Via Sensata DC:* Sensata always pays the leg AGM → DC and the import duty (the DC imports). The freight terms apply to the leg DC → customer: they decide whether the outbound freight (% of revenue) and the insurance are Sensata's cost. Warehouse cost applies.
*Direct to customer:* there is no DC, so no warehouse or outbound cost. The freight terms decide whether the freight AGM → customer, the insurance and the duty are Sensata's cost. With DDP the customs value is the selling price without the duty (and, for the USA, without the transport).

**US situation (September 2026, verify with Trade Compliance).** Non-USMCA goods from Mexico pay a 10% duty (Section 301) on top of the normal (MFN) rate. Auto parts on the Section 232 list pay 25%, but USMCA-qualifying parts are exempt. The USMCA stays in force with a yearly review.

**Freight** = product weight × freight rate per kg for the lane.
""",
    "portfolio": """
Should the three products be one business case or three separate ones? The tab compares four views.

- **Combined** – all three products together; the shared costs (CapEx, RD&E, SG&A, samples, CUF, quicksavings from the sidebar) are paid once.
- **Stand-alone** – one product on its own, carrying the part of the shared costs it would still need alone (sidebar → Portfolio, default 100%).
- **Allocated** – each product carries its share of the shared costs in proportion to its volume. The three allocated NPVs add up to the combined NPV (except for tax effects). This is what the product views in the other tabs show.
- **Incremental** – combined NPV minus the combined NPV without the product. This is the right test for keeping or dropping a product.

**Synergy** = combined NPV − sum of the stand-alone NPVs: the value of sharing the investment.

**Decision rules**
- Incremental NPV < 0 → the product destroys value; reprice, cut cost or drop it.
- Stand-alone NPV < 0 but incremental NPV > 0 → the product only makes sense inside the package.
- A positive combined NPV can hide a product that is subsidised by the others; always show the incremental NPVs next to it.
""",
    "revenue": """
Where the revenue comes from, year by year.
- **Volume** – from the forecast table in the sidebar (Volume & price) × the product split.
- **ASP** – selling price per unit (sidebar → Selling price): price A or price B, the same for all 3 products. The **price-down table** sets the reduction per year. *Year-on-year*: each % is taken from the previous year's price, so the price stays down. *Discount on the quoted price*: the % applies only in that year.
- **Item net revenue** = volume × ASP.
- **Sample net revenue** – revenue from prototypes and samples, booked in the launch year.
- **CUF** – customer upfront funding, e.g. the customer paying part of the tooling.
- **Quicksavings amortization** – an upfront price concession to the customer, spread over the years in proportion to volume (shown as negative revenue).
- **YoY ASP productivity %** – the yearly price change; negative means a price-down.
""",
    "otp": """
What one unit costs to make and deliver (**OTP**), and how that changes over time.

**The building blocks ($/unit)**
- **Material** – MAT from the cost table (pre-filled with the pending cost), adjusted for yield. If it already includes the standard (steady-state) scrap, only the extra launch scrap is added. **Yield** is the share of good parts: at 97% you need material for about 103 units to ship 100.
- **Material overhead (MOH)** – duty and freight of the components to Sensata (MOH in the cost table).
- **CLAM** – make-site conversion cost: direct labour (RES in the cost table), indirect labour & overhead (OH in the cost table), depreciation of existing equipment and depreciation of the new investment.
- **Freight MS→DC** – transport of the finished product from AGM to the Sensata DC (or to the customer on the direct route, when the freight terms make Sensata pay it).
- **Cargo insurance** – only when the freight terms (CIP / CIF) make Sensata buy it.
- **Finished-goods duties** – import duty on the finished product in the market, when Sensata pays it (see the Tariffs tab).

**Learning curve.** At launch, labour and overhead cost more (launch CLAM premium) and yield is lower. Both move to steady state over the years set in the sidebar. Gamma in AGM has its own ramp-up curve.

**How to read the charts**
- The stacked bars are the OTP per unit; the dotted line is the selling price. The gap between them is the margin per unit.
- The **waterfall** shows which components pushed the unit cost up or down from the first to the last year.

**Project savings** = change in OTP × volume. Negative numbers are savings.
""",
    "pl": """
The profit & loss statement in the same layout as the company Excel: rows are line items, columns are years, the last column is the total.

- **Product COGS** = material + CLAM + freight to the market + finished-goods duties.
- **Overhead COGS** = outbound freight + warehouse + COPQ (warranty accrual), each a % of revenue. Warehouse applies only to volume sold via a Sensata DC; outbound freight only when the freight terms to the customer make Sensata pay it.
- **Gross (make) margin** = net revenue − total COGS. Shows how profitable the product itself is.
- **RD&E net** = RD&E labour + expenses − NRE (engineering paid by the customer).
- **SG&A** – extra sales and admin cost caused by the project.
- **Cost of payment terms** – the cost of giving the customer time to pay; depends on the payment days selected.
- **Contribution margin** = gross margin − RD&E − SG&A − payment terms. What the project contributes to the company.

**Annual metrics summary** – the key figures per year, including the yearly change in price (ASP productivity) and in unit cost (OTP productivity).
""",
    "cashflow": """
Profit is not the same as cash. This tab turns the contribution margin into **free cash flow (FCF)**: the money that really comes in or goes out each year.

**The bridge from margin to cash**
- **− Income tax** – only if a tax rate is set in the sidebar.
- **+ Depreciation** – an accounting charge, not a payment. The cash left when the equipment was bought (CapEx), so it is added back.
- **+ Cost of payment terms** – also not a payment; its cash effect is already in the receivables.
- **+ Quicksavings amortization / − Quicksavings paid** – the P&L spreads the concession over the years; in cash it is paid at once.
- **− Capital expenditures** – money spent on new equipment.
- **− Change in working capital** – cash tied up as the business grows: money customers still owe (DSO), stock on hand (DIO), minus money still owed to suppliers (DPO).
- **+ Working capital release** – at the end of the project the tied-up cash comes back.

**Cumulative FCF** is the running total. The year the line crosses zero is the **payback**.

The lower charts show the investment (CapEx, depreciation, remaining book value) and the working capital tied up each year.
""",
    "scenarios": """
**Scenarios** – what if things go better or worse than planned?
Pick a preset (Base, Upside, Downside) and adjust the sliders. Each one changes volume, price, material, CLAM or CapEx by a % versus the base case. The table and chart compare the scenario with the base case.

**Sensitivity (tornado)** – which assumption matters most?
Each lever is moved up and down by the same %, one at a time (the WACC by ±2 points). The longer the bar, the more the NPV reacts, and the more that assumption deserves attention and good data.
""",
    "montecarlo": """
Think of rolling a die: one roll tells you little, but 1,000 rolls show which outcomes are common and which are rare.

Your forecast is one number per assumption, but reality always deviates. Monte Carlo plays the project **1,000+ times**, each time randomly shifting **volume**, **price-downs** and **material savings** within the ranges you set. You get 1,000 possible futures instead of one.

**How to read the results**
- **Mean NPV** – the average result.
- **P5** – the bad case: only 5 in 100 runs are worse.
- **P95** – the good case: only 5 in 100 runs are better.
- **P(NPV > 0)** – in how many out of 100 runs the project is profitable.
- **Histogram** – all results; left of the red line the project loses money, right of it the project creates value.

**In one sentence:** if our forecast is not exactly right, how big is the risk that the project does not pay off?

**Limits.** The volatility sliders decide how much is shuffled: set them too low and the risk looks smaller than it is. It cannot foresee events outside the model, such as the customer cancelling. Press **Run simulation** after changing inputs; the same seed gives the same result.
""",
    "custom": """
A stand-alone calculator for any business case where you already have the year-by-year numbers, without the drivers in the sidebar.

Enter or paste per year: net revenue, COGS, operating expenses (everything below gross margin), the depreciation included in those costs, CapEx and the change in working capital (positive = cash out). The tab calculates gross margin, contribution margin, free cash flow, NPV, IRR and payback with its own discount rate.
""",
    "takeaways": """
All conclusions from the other tabs in one place. Each line has the **conclusion**, the **argument** (the numbers behind it) and the **action**. They update with every change in the inputs, so they always describe the case on the screen.

- ✅ OK – supports the decision as it is.
- ℹ️ Info – context to know when presenting the case.
- ⚠️ Attention – needs data, a check or a decision.
- ❌ Risk – works against the case until it is solved.

Use the download button to paste them into the presentation or the decision log.
""",
}


def show_guide(key, title_key="tab"):
    with st.expander(GUIDE_TITLES[title_key]):
        st.markdown(GUIDE[key])


# =====================================================
# TAKEAWAYS
# =====================================================

TAKEAWAYS = []
_LEVEL = {"ok": ("✅", st.success), "info": ("ℹ️", st.info), "warn": ("⚠️", st.warning), "risk": ("❌", st.error)}


def takeaway(section, level, title, argument, action):
    icon, box = _LEVEL[level]
    TAKEAWAYS.append(dict(Section=section, Level=f"{icon} {level}", Conclusion=title, Argument=argument, Action=action))
    box(f"**{title}**\n\n{argument}\n\n**Action:** {action}")


# =====================================================
# FINANCIAL HELPERS
# =====================================================

def compute_npv(rate, cashflows, excel_convention=True):
    """Excel NPV() discounts the first cash flow by one full period.
    With excel_convention=False the first year is treated as 'today' (not discounted)."""
    start = 1 if excel_convention else 0
    return sum(cf / ((1 + rate) ** (i + start)) for i, cf in enumerate(cashflows))


def compute_irr(cashflows):
    """IRR by bracketing + bisection. Returns None when there is no sign change."""
    if not any(cf > 0 for cf in cashflows) or not any(cf < 0 for cf in cashflows):
        return None

    def f(r):
        return sum(cf / ((1 + r) ** i) for i, cf in enumerate(cashflows))

    grid = [-0.95, -0.8, -0.6, -0.4, -0.2, 0.0, 0.1, 0.2, 0.4, 0.7, 1.0, 2.0, 5.0, 10.0]
    bracket = None
    for a, b in zip(grid[:-1], grid[1:]):
        if f(a) * f(b) <= 0:
            bracket = (a, b)
            break
    if bracket is None:
        return None

    low, high = bracket
    f_low = f(low)
    for _ in range(200):
        mid = (low + high) / 2
        f_mid = f(mid)
        if abs(f_mid) < 1e-7:
            return mid
        if f_low * f_mid < 0:
            high = mid
        else:
            low, f_low = mid, f_mid
    return (low + high) / 2


def compute_payback(cashflows):
    """Years from project start until cumulative cash turns positive for good
    (interpolated within the year). None if it never pays back."""
    if not np.any(np.asarray(cashflows) != 0):
        return None
    cum = np.cumsum(cashflows)
    negative = np.where(cum < 0)[0]
    if len(negative) == 0:
        return 0.0
    j = negative[-1]
    if j == len(cashflows) - 1:
        return None
    return (j + 1) + (-cum[j] / cashflows[j + 1])


def pct(x):
    return f"{x * 100:.1f}%" if x is not None else "n/a"


def years_fmt(x, suffix=""):
    return f"{x:.2f}{suffix}" if x is not None else "> horizon"


def k(x):
    return f"{x:,.0f}"


# =====================================================
# SIDEBAR — INPUTS
# =====================================================

st.sidebar.title("Detailed inputs")
st.sidebar.caption("All money in $k. The quick levers (view, price, what-if) are on the main page. "
                   "Hover the ⓘ icons for definitions; the Explain tab says where every input comes from.")

P = {}

st.sidebar.markdown("#### 1 · Volume & price")
with st.sidebar.expander("Project timeline", expanded=False):
    launch_year = st.selectbox("Launch year (first shipments)", list(range(2024, 2036)), index=3,
                               help="The year the first units are shipped. It stays fixed when you change the settings below.")
    P["launch"] = st.slider("Pre-launch years (CapEx / RD&E only)", 0, 5, 0,
                            help="Years before the launch year with only investment and development spend, no shipments. "
                                 "They are added before the launch year.")
    selling_years = st.slider("Selling years (incl. launch year)", 3, 15, 6,
                              help="Match it to the forecast period. The company Excel uses a 10-year horizon (10Y Total column).")
    P["start_year"] = launch_year - P["launch"]
    P["n"] = P["launch"] + selling_years
    st.caption(f"Project runs {P['start_year']}–{P['start_year'] + P['n'] - 1}, launch in {launch_year}.")

with st.sidebar.expander("Volume & product split", expanded=False):
    sell_years = [P["start_year"] + i for i in range(P["launch"], P["n"])]
    if "vol_store2" not in st.session_state:
        st.session_state["vol_store2"] = {
            sell_years[0] + i: {"vol": v, "HSSI_EU": 33.4, "HSSI_NA": 33.3, "GAMMA": 33.3}
            for i, v in enumerate(DEFAULT_VOLUME_FORECAST)}
    store = st.session_state["vol_store2"]
    vol_df = pd.DataFrame({"Year": [str(y) for y in sell_years],
                           "Volume (k units)": [store.get(y, {}).get("vol") for y in sell_years]})
    for pk in PKEYS:
        vol_df[SHARE_COL[pk]] = [store.get(y, {}).get(pk, 100 / 3) for y in sell_years]
    st.markdown("**Volume forecast (all 3 products) and split per product**")
    edited_vol = st.data_editor(
        vol_df, hide_index=True, disabled=["Year"], num_rows="fixed",
        key=f"vol_editor2_{P['start_year']}_{P['launch']}_{P['n']}",
        column_config={"Volume (k units)": st.column_config.NumberColumn(min_value=0.0, format="%.1f"),
                       **{SHARE_COL[pk]: st.column_config.NumberColumn(min_value=0.0, max_value=100.0, format="%.1f")
                          for pk in PKEYS}},
    )
    share_table, bad_rows = [], []
    for idx, y in enumerate(sell_years):
        row = edited_vol.iloc[idx]
        v = row["Volume (k units)"]
        entry = {"vol": None if pd.isna(v) else float(v)}
        raw = {pk: (0.0 if pd.isna(row[SHARE_COL[pk]]) else float(row[SHARE_COL[pk]])) for pk in PKEYS}
        entry.update(raw)
        store[y] = entry
        s = sum(raw.values())
        if abs(s - 100) > 0.05:
            bad_rows.append(f"{y}: {s:.1f}%")
        share_table.append({pk: (raw[pk] / s if s > 0 else 1 / 3) for pk in PKEYS})
    P["vol_table"] = tuple(store[y]["vol"] for y in sell_years)
    P["share_table"] = share_table
    st.caption("Volume in thousands of units (4.5 = 4,500 units). You can paste columns from Excel. "
               "Split in % of the year's volume; each row should add up to 100%.")
    if bad_rows:
        st.warning("Split does not add up to 100% in " + ", ".join(bad_rows) + ". The model rescales these rows.")

    filled = [j for j, v in enumerate(P["vol_table"]) if v is not None and v > 0]
    if filled and filled[-1] < len(sell_years) - 1:
        P["steady_growth"] = st.slider(
            "Growth for years after the forecast % / year", -20, 60, 0,
            help="Your table has empty years at the end. They continue from the last forecast year at this rate, "
                 "with the split of the last forecast year.")
    else:
        P["steady_growth"] = 0


def price_path(P, base_price, shift=0.0):
    """Selling price per selling year, from the quoted price and the price-down table."""
    path, prev = [], base_price
    for d in P["price_down"]:
        d = d + shift
        prev = (prev if P["price_down_mode"] == "yoy" else base_price) * (1 - d)
        path.append(prev)
    return path


with st.sidebar.expander("Selling price (all 3 products)", expanded=False):
    c1, c2 = st.columns(2)
    P["price_A"] = c1.number_input("Price A ($/unit)", 0.0, 1000.0, 10.0, 0.5, format="%.2f")
    P["price_B"] = c2.number_input("Price B ($/unit)", 0.0, 1000.0, 12.0, 0.5, format="%.2f")
    P["price_scen"], P["asp_all"] = "A", P["price_A"]   # the scenario is chosen on the main page
    st.markdown("**Price-down to the customer**")
    P["price_down_mode"] = "yoy" if st.radio(
        "How the price-down works",
        ["Year-on-year (the price stays down)", "Discount on the quoted price (only in those years)"],
        key="pd_mode",
        help="Year-on-year: each year's % is taken from the previous year's price (usual in automotive LTAs). "
             "Discount: the % is taken from the quoted price only in that year; in years with 0% the quoted price applies."
    ).startswith("Year") else "discount"
    pd_default = pd.DataFrame({"Year": [str(y) for y in sell_years],
                               "Price-down %": [1.0 if i < 2 else 0.0 for i in range(len(sell_years))]})
    pd_ed = st.data_editor(pd_default, hide_index=True, disabled=["Year"], num_rows="fixed",
                           key=f"pdown_{P['start_year']}_{P['launch']}_{P['n']}",
                           column_config={"Price-down %": st.column_config.NumberColumn(min_value=-20.0, max_value=50.0,
                                                                                       format="%.2f")})
    P["price_down"] = [0.0 if pd.isna(v) else float(v) / 100 for v in pd_ed["Price-down %"]]
    for lbl, pr in (("A", P["price_A"]), ("B", P["price_B"])):
        st.caption(f"Price {lbl}: " + " → ".join(f"{y}: {v:.4f}" for y, v in zip(sell_years, price_path(P, pr))))


COST_COLS = {"mat": "Material MAT", "moh": "Material overhead MOH", "dl": "Direct labour RES",
             "oh": "Indirect & overhead OH", "weight_g": "Weight (g)"}


def std_cost_table(basis):
    rows = []
    for pk in PKEYS:
        s = std_split(PRODUCTS[pk]["costs"][basis])
        s["weight_g"] = PRODUCTS[pk]["weight_g"]
        rows.append({"Product": PNAME[pk], **{COST_COLS[c]: s[c] for c in COST_COLS}})
    return pd.DataFrame(rows)


# Material quote received directly (overrides the Item Readiness Report MAT only; MOH/RES/OH stay as reported).
MATERIAL_QUOTE = {"HSSI_EU": 4.885, "HSSI_NA": 4.885, "GAMMA": 5.852}


def default_cost_table():
    t = std_cost_table("Pending")
    for idx, pk in enumerate(PKEYS):
        if pk in MATERIAL_QUOTE:
            t.loc[idx, COST_COLS["mat"]] = MATERIAL_QUOTE[pk]
    return t


st.sidebar.markdown("#### 2 · Products & unit cost")
with st.sidebar.expander("Unit costs per product (AGM, $/unit)", expanded=False):
    if "cost_table" not in st.session_state:
        st.session_state["cost_table"] = default_cost_table()
        st.session_state["cost_src"] = "Pending"
        st.session_state["cost_ver"] = 0
    if st.button("Reset to pending costs", help="Overwrites the table with the pending costs from the Item Readiness Report "
                                                "(drops the material quote below and any other manual edits)."):
        st.session_state["cost_table"] = std_cost_table("Pending")
        st.session_state["cost_src"] = "Pending"
        st.session_state["cost_ver"] += 1
    if st.button("Apply material quote", help="Reloads the pending costs and re-applies the received material quote "
                                              "(4.885 $/unit HSSI, 5.852 $/unit Gamma) on top, without touching any "
                                              "other manual edits you may have made to MOH/RES/OH."):
        st.session_state["cost_table"] = default_cost_table()
        st.session_state["cost_src"] = "Pending"
        st.session_state["cost_ver"] += 1
    if st.button("Clear table (enter everything manually)"):
        empty = std_cost_table("Pending")
        for col in list(COST_COLS.values())[:-1]:
            empty[col] = 0.0
        st.session_state["cost_table"] = empty
        st.session_state["cost_src"] = None
        st.session_state["cost_ver"] += 1
    cost_ed = st.data_editor(
        st.session_state["cost_table"], hide_index=True, disabled=["Product"], num_rows="fixed",
        key=f"cost_editor_{st.session_state['cost_ver']}",
        column_config={**{COST_COLS[c]: st.column_config.NumberColumn(min_value=0.0, format="%.5f")
                          for c in ["mat", "moh", "dl", "oh"]},
                       "Weight (g)": st.column_config.NumberColumn(min_value=0.0, format="%.1f")})
    P["costs"] = {}
    for idx, pk in enumerate(PKEYS):
        r = cost_ed.iloc[idx]
        P["costs"][pk] = {c: (0.0 if pd.isna(r[COST_COLS[c]]) else float(r[COST_COLS[c]])) for c in COST_COLS}
    P["cost_src"] = st.session_state["cost_src"]
    # which cells differ from the standard costs they were loaded from
    edited = []
    if P["cost_src"]:
        ref = std_cost_table(P["cost_src"])
        for idx, pk in enumerate(PKEYS):
            for c, col in COST_COLS.items():
                if abs(P["costs"][pk][c] - ref.iloc[idx][col]) > 1e-9:
                    edited.append(f"{PNAME[pk]} {col}")
    P["cost_edited"] = edited
    src_txt = "pending cost" if P["cost_src"] else "manual entry"
    st.caption(f"Pre-filled from: {src_txt}. Every cell can be edited. MAT = parts cost; MOH = duty & freight of "
               "the components; RES = direct labour; OH = indirect labour & other overhead.")
    if edited:
        st.info("Edited by hand: " + ", ".join(edited))

with st.sidebar.expander("Product portfolio (specific costs, markets)", expanded=False):
    prod_df = pd.DataFrame({
        "Product": [PNAME[pk] for pk in PKEYS],
        "Specific CapEx at launch ($k)": [0.0, 0.0, 0.0],
        "Specific RD&E ($k)": [0.0, 0.0, 0.0],
    })
    prod_ed = st.data_editor(
        prod_df, hide_index=True, disabled=["Product"], num_rows="fixed", key="prod_editor",
        column_config={
            "Specific CapEx at launch ($k)": st.column_config.NumberColumn(min_value=0.0, format="%.1f"),
            "Specific RD&E ($k)": st.column_config.NumberColumn(min_value=0.0, format="%.1f"),
        })
    st.caption("Specific CapEx / RD&E = only what this product needs on top of the shared project costs below. "
               "The selling price is set above (Selling price).")
    gamma_us = st.slider("Gamma sold in the USA %", 0, 100, 50,
                         help="HSSI NA goes 100% to the USA, HSSI EU 100% to Europe. Gamma is split.")
    us_share = {"HSSI_EU": 0.0, "HSSI_NA": 1.0, "GAMMA": gamma_us / 100}
    P["products"] = {}
    for idx, pk in enumerate(PKEYS):
        r = prod_ed.iloc[idx]
        P["products"][pk] = dict(asp=price_path(P, P["asp_all"])[0] if P["price_down"] else P["asp_all"],
                                 capex=float(r["Specific CapEx at launch ($k)"] or 0.0),
                                 rde=float(r["Specific RD&E ($k)"] or 0.0), us_share=us_share[pk])
    P["std_yielded"] = st.checkbox("Material cost already includes steady-state scrap", value=True,
                                      help="Standard costs normally include planned scrap. Ticked: only the extra "
                                           "launch scrap (launch yield vs steady-state yield) is added.")
    P["oh_dep_share"] = st.slider("Depreciation share of overhead (OH) %", 0, 100, 0,
                                  help="Part of the overhead that is depreciation of existing equipment. "
                                       "It is shown as 'Depreciation standard make' and added back in cash flow. "
                                       "0% = conservative (all overhead is cash).")
    st.markdown("**Gamma in AGM – ramp-up**")
    P["gamma_ramp"] = st.checkbox("Model Gamma AGM ramp-up", value=True,
                                  help="Gamma's conversion cost is ~10x that of HSSI in the same plant (ramp-up). "
                                       "Ticked: it starts at the level in the cost table and falls to the steady-state level.")
    g_conv = P["costs"]["GAMMA"]["dl"] + P["costs"]["GAMMA"]["oh"]
    h_conv = P["costs"]["HSSI_NA"]["dl"] + P["costs"]["HSSI_NA"]["oh"]
    P["gamma_clam_launch"] = g_conv
    st.caption(f"Launch level = Gamma RES + OH from the cost table: {g_conv:.5f} $/unit.")
    P["gamma_clam_steady"] = st.number_input("Gamma CLAM at steady state ($/unit)", 0.01, 50.0,
                                             max(round(h_conv, 5), 0.01), 0.01, format="%.5f",
                                             key=f"g_steady_{round(h_conv, 5)}",
                                             help="Default = HSSI NA RES + OH from the cost table (same plant, mature process).")
    P["gamma_years"] = st.slider("Gamma AGM years to steady state", 1, 6, 3)

with st.sidebar.expander("Other net revenue"):
    P["sample_nr"] = st.number_input("Sample net revenue ($k, pre-launch/launch)", 0.0, value=0.0, step=10.0,
                                     help="Revenue from prototype / sample sales. Booked in the launch year.")
    P["cuf"] = st.number_input("CUF – customer upfront funding ($k)", 0.0, value=0.0, step=10.0,
                               help="Customer contribution (e.g. to tooling), booked as non-item revenue in the launch year.")
    P["qs_paid"] = st.number_input("Quicksavings paid ($k)", 0.0, value=0.0, step=50.0,
                                   help="Upfront price concession paid to the customer at launch. "
                                        "P&L: amortized against revenue in proportion to volume. Cash: paid out in full at launch.")

with st.sidebar.expander("Material productivity & yield"):
    P["mat_prod"] = st.slider("Material productivity % / year", 0.0, 15.0, 2.0,
                              help="Yearly material cost reduction (volume, negotiated and design savings). "
                                   "Applied to MAT and MOH.")
    P["yield_launch"] = st.slider("Yield at launch %", 80.0, 100.0, 96.5)
    P["yield_steady"] = st.slider("Steady-state yield %", 80.0, 100.0, 98.0,
                                  help="Yielded material = unyielded material / yield.")

with st.sidebar.expander("CLAM learning curve"):
    st.caption("CLAM = labour, overhead, depreciation and supplies of the make site (RES + OH).")
    P["labour_infl"] = st.slider("Labour rate inflation % / year", 0.0, 15.0, 3.0, help="Applied to direct labour (RES).")
    P["clam_premium"] = st.slider("Launch CLAM premium (x steady-state)", 1.0, 3.0, 1.3,
                                  help="Labour and overhead are higher at launch (learning curve). Depreciation is not "
                                       "affected. Gamma in AGM uses its own ramp-up when that option is ticked.")
    P["conv_years"] = st.slider("Years to reach steady-state CLAM & yield", 0, 5, 2)

st.sidebar.markdown("#### 3 · Logistics & duties")
with st.sidebar.expander("Finished-goods freight & duties"):
    st.caption("Rates as of Sep 2026 – verify with Trade Compliance. The rate below applies when the origin is "
               "NOT preferential; tick 'Preferential origin' for 0%.")
    st.markdown("**Sales route (decides the customs value)**")
    route_help = ("Via Sensata DC: duty on the intercompany invoice (make-site cost + mark-up). "
                  "Direct to customer: duty on the selling price (ASP), which is higher.")
    P["route"] = {
        "US": "dc" if st.selectbox("USA", [ROUTE_DC, ROUTE_DIRECT], key="route_us", help=route_help) == ROUTE_DC else "direct",
        "EU": "dc" if st.selectbox("Europe", [ROUTE_DC, ROUTE_DIRECT], key="route_eu", help=route_help) == ROUTE_DC else "direct",
    }
    st.markdown("**Freight terms to the customer (Incoterms 2020)**")
    P["incoterm"] = {}
    for m, lbl in (("US", "USA"), ("EU", "Europe")):
        r_ = P["route"][m]
        other = "direct" if r_ == "dc" else "dc"
        leg = "Sensata DC → customer" if r_ == "dc" else "AGM → customer"
        sel = st.selectbox(f"{lbl}: {leg}", TERM_LIST, index=TERM_LIST.index(DEFAULT_TERM[r_]), key=f"inc_{m}_{r_}",
                           help=INCOTERMS[DEFAULT_TERM[r_]]["desc"] + " Hover the list or see the Tariffs tab for all terms.")
        st.caption(INCOTERMS[sel]["desc"])
        if INCOTERMS[sel]["sea"] and (m == "US" or r_ == "dc"):
            st.warning(f"{sel.split(' –')[0]} is a sea-only term; for truck or multimodal transport use FCA, CPT or CIP.")
        P["incoterm"][m] = {r_: sel, other: DEFAULT_TERM[other]}
    P["ins_pct"] = st.number_input("Cargo insurance % of invoice value (CIP / CIF)", 0.0, 5.0, 0.1, 0.05,
                                   help="Placeholder – ask Logistics for the insurance rate.")
    P["tp_markup"] = st.number_input("Intercompany mark-up on make-site cost %", 0.0, 100.0, 10.0, 1.0,
                                     help="Used only for the 'via Sensata DC' route. Placeholder: the real transfer "
                                          "price is set by Sensata Tax (arm's length).")
    P["s232"] = st.checkbox("Section 232 auto parts (25%) applies to the USA", value=False,
                            help="Only if the HTS code (9026.20) is on the auto parts list and the part is not "
                                 "USMCA-qualifying. Replaces the 10% additional duty (no stacking assumed).")
    lane_def = {("MX", "US"): (1.0, 1.7, 10.0, False), ("MX", "EU"): (2.5, 2.0, 0.0, False)}
    lane_help = {("MX", "US"): "USMCA: 0% if the rules of origin are met (component origin decides – material is ~90% of cost).",
                 ("MX", "EU"): "EU–Mexico agreement: 0% if the Mexican origin is proven."}
    P["freight_kg"], P["duty"] = {}, {}
    for lane in LANES:
        fr, mfn, add, pref = lane_def[lane]
        st.markdown(f"**{lane[0]} → {lane[1]}**")
        c1, c2, c3 = st.columns(3)
        P["freight_kg"][lane] = c1.number_input("Freight $/kg", 0.0, 50.0, fr, 0.1, key=f"fr_{lane}")
        mfn_v = c2.number_input("MFN %", 0.0, 50.0, mfn, 0.1, key=f"mfn_{lane}")
        add_v = c3.number_input("Extra %", 0.0, 100.0, add, 0.5, key=f"add_{lane}")
        pref_v = st.checkbox("Preferential origin (0%)", value=pref, key=f"pref_{lane}", help=lane_help[lane])
        P["duty"][lane] = dict(mfn=mfn_v / 100, add=add_v / 100, pref=pref_v)

with st.sidebar.expander("Logistics & overhead COGS"):
    P["outbound_pct"] = st.slider("Outbound freight % of item NR", 0.0, 5.0, 1.0)
    P["warehouse_pct"] = st.slider("Warehouse % of item NR", 0.0, 5.0, 0.4)
    P["copq_pct"] = st.slider("COPQ / warranty accrual % of item NR", 0.0, 5.0, 1.28,
                              help="Cost of Poor Quality. Standard BU accrual per the Data Register.")

st.sidebar.markdown("#### 4 · Investment, RD&E & SG&A")
with st.sidebar.expander("Additional investment (CapEx, shared)"):
    P["capex_y1"] = st.number_input("CapEx year 1 ($k)", 0.0, value=0.0, step=10.0)
    P["capex_y2"] = st.number_input("CapEx year 2 ($k)", 0.0, value=0.0, step=10.0)
    P["capex_launch"] = st.number_input("CapEx in launch year ($k)", 0.0, value=105.0, step=10.0)
    P["dep_life"] = st.slider("Useful life (years, straight-line)", 3, 20, 10,
                              help="Depreciation starts when the asset is in service (launch year or later), full-year convention as in Excel.")

with st.sidebar.expander("RD&E (shared)"):
    st.caption("Program-specific RD&E per year, $k (as in the Excel 'RD&E Output'): labour, non-labour "
               "expenses and NRE paid by the customer (NRE reduces the RD&E cost).")
    proj_years = [P["start_year"] + i for i in range(P["n"])]
    rde_default = pd.DataFrame({"Year": [str(y) for y in proj_years],
                                "Labour": [2000 / 3 if i < 3 else 0.0 for i in range(P["n"])],
                                "Expenses": [800 / 3 if i < 3 else 0.0 for i in range(P["n"])],
                                "NRE": [500 / 3 if i < 3 else 0.0 for i in range(P["n"])]})
    rde_ed = st.data_editor(rde_default, hide_index=True, disabled=["Year"], num_rows="fixed",
                            key=f"rde_{P['start_year']}_{P['n']}",
                            column_config={c: st.column_config.NumberColumn(min_value=0.0, format="%.1f")
                                           for c in ["Labour", "Expenses", "NRE"]})
    P["rde_table"] = {c: np.array([0.0 if pd.isna(v) else float(v) for v in rde_ed[c]]) for c in ["Labour", "Expenses", "NRE"]}
    st.caption(f"Totals: labour {P['rde_table']['Labour'].sum():,.0f}, expenses {P['rde_table']['Expenses'].sum():,.0f}, "
               f"NRE {P['rde_table']['NRE'].sum():,.0f} $k.")
    P["rde_net_of_nre"] = st.checkbox("Program-specific RD&E after NRE (net)", value=True,
                                      help="Used for NPD Effectiveness and Return on RD&E. Ticked: RD&E labour + "
                                           "expenses − NRE. Unticked: before NRE (labour + expenses).")

with st.sidebar.expander("SG&A & payment terms"):
    P["sga_fixed"] = st.number_input("Incremental SG&A, fixed ($k / year from launch, shared)", 0.0, value=100.0, step=10.0)
    P["sga_pct"] = st.slider("Incremental SG&A % of item NR", 0.0, 10.0, 0.0)
    P["pay_days"] = st.selectbox("Contracted payment terms (days)", list(PAYMENT_TERMS_TABLE.keys()), index=2,
                                 help="Maps to the 'Payments terms' table: cost as % of item NR.")
    P["pay_pct"] = PAYMENT_TERMS_TABLE[P["pay_days"]]
    st.caption(f"Cost of payment terms: {P['pay_pct']:.1f}% of item NR")

st.sidebar.markdown("#### 5 · Cash flow & decision")
with st.sidebar.expander("Working capital"):
    P["dso"] = st.number_input("Days sales outstanding (DSO)", 0, 365, 60,
                               help="Receivables = DSO/365 x item NR. Money customers still owe you.")
    P["dio"] = st.number_input("Days inventory outstanding (DIO)", 0, 365, 70,
                               help="Inventory = DIO/365 x product COGS (cash cost).")
    P["dpo"] = st.number_input("Days payable outstanding (DPO)", 0, 365, 63,
                               help="Payables = DPO/365 x material spend. Money you still owe suppliers; reduces working capital.")
    P["wc_release"] = st.checkbox("Release working capital at end of horizon", value=True,
                                  help="Adds back the remaining working capital in the last year (common in project valuation). Excel does not do this.")

with st.sidebar.expander("Portfolio"):
    P["standalone_share"] = st.slider("Shared costs a product still needs on its own %", 0, 100, 100,
                                      help="Used in the stand-alone view of the 'Combined vs separate' tab: how much of "
                                           "the shared CapEx, RD&E, SG&A (and samples, CUF, quicksavings) one product "
                                           "would need if it were done alone. 100% = the full line and development.")

with st.sidebar.expander("Tax & conventions"):
    P["tax_rate"] = st.slider("Income tax rate %", 0.0, 35.0, 0.0,
                              help="Excel has a placeholder 'Income tax?'. 0% = pre-tax analysis. Simple model: tax on positive contribution margin, no loss carry-forward.")
    P["add_back_std_dep"] = st.checkbox("Add back standard-make depreciation in cash flow", value=True,
                                        help="Treats existing make-site assets as sunk (as Excel does). Untick if the project needs new capacity you are not modelling as CapEx.")
    P["excel_npv"] = st.checkbox("Excel NPV convention (discount year 1)", value=True,
                                 help="Excel NPV() discounts the first year by one period. Untick to treat year 1 as 'today'.")

with st.sidebar.expander("Investment decision", expanded=False):
    P["wacc"] = st.slider("WACC / discount rate %", 0.0, 30.0, 12.0) / 100
    P["payback_hurdle"] = st.slider("Payback hurdle (< years)", 1, 10, 3)
    st.markdown("**Manufacturing margin hurdles**")
    mm_default = pd.DataFrame({"Benchmark": ["Tire Management Solutions Worldwide", "TPMS Worldwide",
                                             "Sensata Worldwide"],
                               "Hurdle %": [37.7, 43.3, 40.3]})
    mm_ed = st.data_editor(mm_default, num_rows="dynamic", hide_index=True, key="mm_hurdles",
                           column_config={"Hurdle %": st.column_config.NumberColumn(min_value=0.0, max_value=100.0,
                                                                                    format="%.1f")})
    P["mm_hurdles"] = [(str(r["Benchmark"]).strip(), float(r["Hurdle %"])) for _, r in mm_ed.iterrows()
                       if not pd.isna(r["Hurdle %"]) and str(r["Benchmark"]).strip() not in ("", "None", "nan")]
    st.caption("From the company Excel (Investment Decision). Add, rename or remove rows as needed.")


# =====================================================
# CORE MODEL
# =====================================================

UNIT_COLS = ["ASP ($/unit)", "Material, yielded ($/unit)", "Yield %", "Material overhead MOH ($/unit)",
             "Material incl. MOH ($/unit)", "Direct labour ($/unit)", "Indirect labour & overhead ($/unit)",
             "Depreciation standard make ($/unit)", "Additional investment depreciation ($/unit)", "CLAM ($/unit)",
             "Freight MS→DC ($/unit)", "Cargo insurance ($/unit)", "Finished-goods duties ($/unit)",
             "OTP / unit cost ($/unit)"]
MONEY_COLS = ["Item net revenue", "Sample net revenue", "CUF", "Quicksavings amortization", "Total net revenue",
              "Material", "CLAM", "Freight MS→DC", "Cargo insurance", "Finished-goods duties", "Product COGS",
              "Outbound freight", "Warehouse", "COPQ (warranty)", "Overhead COGS", "Total COGS", "Gross (make) margin",
              "RD&E labour", "RD&E expenses", "NRE (customer funded)", "RD&E net", "SG&A", "Cost of payment terms",
              "Contribution margin", "Income tax", "+ Additional investment depreciation",
              "+ Standard make depreciation", "+ Cost of payment terms (non-cash)", "+ Quicksavings amortization",
              "- Quicksavings paid", "- Capital expenditures", "- Change in working capital",
              "+ Working capital release", "Free cash flow", "CapEx", "Book value", "Receivables (DSO)",
              "Inventory (DIO)", "Payables (DPO)", "Working capital"]


def duty_rate(P, lane):
    """Duty rate (fraction) on the finished good for a lane."""
    d = P["duty"][lane]
    if d["pref"]:
        return 0.0
    extra = 0.25 if (lane[1] == "US" and P["s232"]) else d["add"]  # Section 232 replaces the 10% (no stacking)
    return d["mfn"] + extra


def customs_value(P, market, asp, make_cost, freight):
    """Duty base per unit on the intercompany invoice (via Sensata DC):
    make-site cost x (1 + mark-up); the EU adds freight to the border (CIF), the USA does not (FOB)."""
    tp = make_cost * (1 + P["tp_markup"] / 100)
    return tp + (freight if market == "EU" else 0.0)


def term_of(P, market, route=None):
    route = route or P["route"][market]
    return P["incoterm"][market][route]


def fg_leg(P, pk, market, asp, make_cost):
    """What Sensata pays per unit to get one unit to the customer in `market`, given the sales route and the
    freight terms. Works with numbers or numpy arrays."""
    lane = ("MX", market)
    fr = P["costs"][pk]["weight_g"] / 1000 * P["freight_kg"][lane]
    rate = duty_rate(P, lane)
    t = INCOTERMS[term_of(P, market)]
    ins = P["ins_pct"] / 100 * asp if t["insurance"] else 0.0 * asp
    if P["route"][market] == "dc":
        # Sensata ships to its own DC and imports there; the terms apply to the DC -> customer leg
        cv = customs_value(P, market, asp, make_cost, fr)
        return dict(freight=fr, insurance=ins, duty=rate * cv, cv=cv, rate=rate, duty_payer="Sensata (DC imports)",
                    warehouse=1.0, outbound=1.0 if t["freight"] else 0.0, lane_freight=fr)
    # direct: AGM -> customer, no DC
    if t["duty"]:  # DDP: invoice includes the duty (and the transport)
        cv = (asp - fr - ins) / (1 + rate) if market == "US" else asp / (1 + rate)
        duty, payer = rate * cv, "Sensata (DDP)"
    else:
        cv, duty, payer = asp, 0.0 * asp, "Customer"
    return dict(freight=fr if t["freight"] else 0.0, insurance=ins, duty=duty, cv=cv, rate=rate, duty_payer=payer,
                warehouse=0.0, outbound=0.0, lane_freight=fr)


def build_volumes(P, vol_mult=1.0, steady_growth=None):
    """Total volume per year (k units) and the product split per year (fractions)."""
    n, L = P["n"], P["launch"]
    sg = P["steady_growth"] if steady_growth is None else steady_growth
    total = np.zeros(n)
    shares = {pk: np.zeros(n) for pk in PKEYS}
    table = list(P["vol_table"])
    filled = [j for j, v in enumerate(table) if v is not None and v > 0]
    last = filled[-1] if filled else -1
    for j in range(len(table)):
        i = L + j
        if j <= last:
            total[i] = (table[j] or 0.0) * vol_mult
            src = j
        elif last >= 0:
            total[i] = total[i - 1] * (1 + sg / 100)
            src = last
        else:
            continue
        for pk in PKEYS:
            shares[pk][i] = P["share_table"][src][pk]
    return total, shares


def lifetime_shares(P, included):
    """Share of each included product in the total volume over the horizon (used to allocate shared costs)."""
    total, shares = build_volumes(P)
    w = {pk: float((total * shares[pk]).sum()) for pk in included}
    s = sum(w.values())
    return {pk: (w[pk] / s if s > 0 else 1 / len(included)) for pk in included}


def product_cost_base(P, pk):
    """AGM cost blocks for the steady state + launch CLAM premium for this product."""
    c = P["costs"][pk]
    b = dict(mat=c["mat"], moh=c["moh"], dl=c["dl"], oh=c["oh"])
    premium, years = P["clam_premium"], P["conv_years"]
    if pk == "GAMMA" and P["gamma_ramp"]:
        conv = b["dl"] + b["oh"]
        if conv > 0:
            f = P["gamma_clam_steady"] / conv
            b["dl"], b["oh"] = b["dl"] * f, b["oh"] * f
            premium = conv / P["gamma_clam_steady"]
        years = P["gamma_years"]
    return b, premium, years


def run_product(P, pk, factor, vol_mult=1.0, asp_mult=1.0, mat_mult=1.0, clam_mult=1.0, capex_mult=1.0,
                asp_shift=0.0, mat_prod=None, steady_growth=None):
    """One product. `factor` = share of the shared project costs (CapEx, RD&E, SG&A fixed, samples, CUF, QS)
    carried by this product. Returns a dict of yearly arrays."""
    n, L = P["n"], P["launch"]
    cfg = P["products"][pk]
    mp = P["mat_prod"] if mat_prod is None else mat_prod

    # ---------- Volume & ASP ----------
    vol_mult, mat_mult = vol_mult * P.get("whatif_vol", 1.0), mat_mult * P.get("whatif_mat", 1.0)
    total, shares = build_volumes(P, vol_mult, steady_growth)
    vol = total * shares[pk]
    selling = vol > 0
    asp = np.zeros(n)
    path = price_path(P, P["asp_all"] * asp_mult, asp_shift / 100)   # quoted price -> price-down table
    for i in range(L, n):
        asp[i] = path[i - L] if i - L < len(path) else (path[-1] if path else P["asp_all"] * asp_mult)

    # ---------- Net revenue ----------
    item_nr = vol * asp
    sample_nr, cuf = np.zeros(n), np.zeros(n)
    if L < n:
        sample_nr[L] = P["sample_nr"] * factor
        cuf[L] = P["cuf"] * factor
    qs_total = P["qs_paid"] * factor
    qs_amort = -qs_total * vol / vol.sum() if vol.sum() > 0 else np.zeros(n)
    total_nr = item_nr + sample_nr + cuf + qs_amort

    # ---------- Learning curve ----------
    ysl_arr = np.arange(n) - L
    base, premium0, clam_years = product_cost_base(P, pk)
    prog = np.clip(ysl_arr / P["conv_years"], 0, 1) if P["conv_years"] > 0 else np.ones(n)
    prog_clam = np.clip(ysl_arr / clam_years, 0, 1) if clam_years > 0 else np.ones(n)
    years_since = np.maximum(ysl_arr, 0)

    # ---------- Material ($/unit): MAT + MOH ----------
    matf = mat_mult * (1 - mp / 100) ** years_since
    mat_unyielded = base["mat"] * matf
    yld = (P["yield_launch"] + (P["yield_steady"] - P["yield_launch"]) * prog) / 100
    if P["std_yielded"]:
        mat_yielded = mat_unyielded * (P["yield_steady"] / 100) / yld
    else:
        mat_yielded = mat_unyielded / yld
    moh_unit = base["moh"] * matf * selling
    mat_yielded = mat_yielded * selling
    material_unit = mat_yielded + moh_unit

    # ---------- CLAM ($/unit): RES + OH ----------
    premium = premium0 + (1 - premium0) * prog_clam
    dep_share = P["oh_dep_share"] / 100
    direct_labour = base["dl"] * (1 + P["labour_infl"] / 100) ** years_since * premium * clam_mult * selling
    indirect = base["oh"] * (1 - dep_share) * premium * clam_mult * selling
    std_dep_unit = base["oh"] * dep_share * selling

    # ---------- CapEx & depreciation ($k) ----------
    capex = np.zeros(n)
    capex[0] += P["capex_y1"] * capex_mult * factor
    if n > 1:
        capex[1] += P["capex_y2"] * capex_mult * factor
    if L < n:
        capex[L] += (P["capex_launch"] * factor + cfg["capex"]) * capex_mult
    add_dep = np.zeros(n)
    for spend_year in range(n):
        if capex[spend_year] <= 0:
            continue
        in_service = max(spend_year, L)
        for kk in range(in_service, min(in_service + P["dep_life"], n)):
            add_dep[kk] += capex[spend_year] / P["dep_life"]
    book_value = np.cumsum(capex) - np.cumsum(add_dep)
    add_dep_unit = np.divide(add_dep, vol, out=np.zeros(n), where=vol > 0)
    clam_unit = direct_labour + indirect + std_dep_unit + add_dep_unit

    # ---------- Finished goods: freight & duties to the market(s) ($/unit) ----------
    freight_unit, ins_unit, duty_unit = np.zeros(n), np.zeros(n), np.zeros(n)
    wh_share, ob_share = 0.0, 0.0
    for m, sh in (("US", cfg["us_share"]), ("EU", 1 - cfg["us_share"])):
        if sh <= 0:
            continue
        leg = fg_leg(P, pk, m, asp, material_unit + clam_unit)
        freight_unit += sh * leg["freight"]
        ins_unit += sh * leg["insurance"]
        duty_unit += sh * leg["duty"]
        wh_share += sh * leg["warehouse"]
        ob_share += sh * leg["outbound"]
    freight_unit, ins_unit, duty_unit = freight_unit * selling, ins_unit * selling, duty_unit * selling
    otp = material_unit + clam_unit + freight_unit + ins_unit + duty_unit

    # ---------- COGS ($k) ----------
    material_k = material_unit * vol
    clam_k = (direct_labour + indirect + std_dep_unit) * vol + add_dep
    freight_k, ins_k, duty_k = freight_unit * vol, ins_unit * vol, duty_unit * vol
    product_cogs = material_k + clam_k + freight_k + ins_k + duty_k
    outbound = item_nr * P["outbound_pct"] / 100 * ob_share   # DC -> customer, only if Sensata pays (terms)
    warehouse = item_nr * P["warehouse_pct"] / 100 * wh_share  # only volume sold via a Sensata DC
    copq = item_nr * P["copq_pct"] / 100
    overhead_cogs = outbound + warehouse + copq
    total_cogs = product_cogs + overhead_cogs
    gross_margin = total_nr - total_cogs

    # ---------- RD&E, SG&A, payment terms ($k) ----------
    tab = P["rde_table"]
    rde_labour = tab["Labour"][:n] * factor
    nre = tab["NRE"][:n] * factor
    prof = tab["Labour"][:n] + tab["Expenses"][:n]            # product-specific RD&E follows the same profile
    w = prof / prof.sum() if prof.sum() > 0 else np.eye(1, n, 0).ravel()
    rde_exp = tab["Expenses"][:n] * factor + cfg["rde"] * w
    rde_net = rde_labour + rde_exp - nre
    sga = P["sga_fixed"] * factor * (ysl_arr >= 0) + item_nr * P["sga_pct"] / 100
    pay_terms = item_nr * P["pay_pct"] / 100
    contribution = gross_margin - rde_net - sga - pay_terms
    tax = np.maximum(contribution, 0) * P["tax_rate"] / 100

    # ---------- Working capital ($k) ----------
    cash_product_cost = product_cogs - std_dep_unit * vol - add_dep
    ar = P["dso"] / 365 * item_nr
    inventory = P["dio"] / 365 * cash_product_cost
    ap = P["dpo"] / 365 * material_k
    wc = ar + inventory - ap
    delta_wc = np.diff(np.concatenate([[0.0], wc]))
    wc_release = np.zeros(n)
    if P["wc_release"]:
        wc_release[-1] = wc[-1]

    # ---------- Free cash flow ($k) ----------
    std_dep_k = std_dep_unit * vol if P["add_back_std_dep"] else np.zeros(n)
    qs_paid = np.zeros(n)
    if L < n:
        qs_paid[L] = qs_total
    fcf = (contribution - tax + add_dep + std_dep_k + pay_terms
           - qs_amort - qs_paid - capex - delta_wc + wc_release)

    return {
        "Volume (k units)": vol, "ASP ($/unit)": asp * selling, "Item net revenue": item_nr,
        "Sample net revenue": sample_nr, "CUF": cuf, "Quicksavings amortization": qs_amort,
        "Total net revenue": total_nr,
        "Material, yielded ($/unit)": mat_yielded, "Yield %": yld * 100 * selling,
        "Material overhead MOH ($/unit)": moh_unit, "Material incl. MOH ($/unit)": material_unit,
        "Direct labour ($/unit)": direct_labour, "Indirect labour & overhead ($/unit)": indirect,
        "Depreciation standard make ($/unit)": std_dep_unit,
        "Additional investment depreciation ($/unit)": add_dep_unit, "CLAM ($/unit)": clam_unit,
        "Freight MS→DC ($/unit)": freight_unit, "Cargo insurance ($/unit)": ins_unit,
        "Finished-goods duties ($/unit)": duty_unit,
        "OTP / unit cost ($/unit)": otp,
        "Material": material_k, "CLAM": clam_k, "Freight MS→DC": freight_k, "Cargo insurance": ins_k, "Finished-goods duties": duty_k,
        "Product COGS": product_cogs, "Outbound freight": outbound, "Warehouse": warehouse,
        "COPQ (warranty)": copq, "Overhead COGS": overhead_cogs, "Total COGS": total_cogs,
        "Gross (make) margin": gross_margin, "RD&E labour": rde_labour, "RD&E expenses": rde_exp,
        "NRE (customer funded)": -nre, "RD&E net": rde_net, "SG&A": sga, "Cost of payment terms": pay_terms,
        "Contribution margin": contribution, "Income tax": -tax,
        "+ Additional investment depreciation": add_dep, "+ Standard make depreciation": std_dep_k,
        "+ Cost of payment terms (non-cash)": pay_terms, "+ Quicksavings amortization": -qs_amort,
        "- Quicksavings paid": -qs_paid, "- Capital expenditures": -capex, "- Change in working capital": -delta_wc,
        "+ Working capital release": wc_release, "Free cash flow": fcf, "CapEx": capex, "Book value": book_value,
        "Receivables (DSO)": ar, "Inventory (DIO)": inventory, "Payables (DPO)": -ap, "Working capital": wc,
    }


def combine(runs, P, rate_delta=0.0, full=True):
    """Add product runs into one business case. Tax is recomputed on the combined contribution margin."""
    n, L = P["n"], P["launch"]
    rate = max(P["wacc"] + rate_delta, -0.99)
    out = {c: sum(r[c] for r in runs) for c in MONEY_COLS}
    vol = sum(r["Volume (k units)"] for r in runs)
    pretax_fcf = out["Free cash flow"] - out["Income tax"]
    tax = np.maximum(out["Contribution margin"], 0) * P["tax_rate"] / 100
    out["Income tax"] = -tax
    out["Free cash flow"] = pretax_fcf - tax
    fcf = out["Free cash flow"]
    npv = compute_npv(rate, fcf, P["excel_npv"])
    if not full:
        return {"npv": npv}

    for c in UNIT_COLS:  # volume-weighted averages
        out[c] = np.divide(sum(r[c] * r["Volume (k units)"] for r in runs), vol, out=np.zeros(n), where=vol > 0)
    out["Volume (k units)"] = vol
    years = [str(P["start_year"] + i) for i in range(n)]
    df = pd.DataFrame({"Year": years, **out})
    selling = vol > 0
    total_nr = df["Total net revenue"].to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        df["Gross margin %"] = np.where(total_nr != 0, df["Gross (make) margin"] / total_nr * 100, np.nan)
        df["Contribution margin %"] = np.where(total_nr != 0, df["Contribution margin"] / total_nr * 100, np.nan)
        otp, asp = df["OTP / unit cost ($/unit)"].to_numpy(), df["ASP ($/unit)"].to_numpy()
        otp_prev, asp_prev = np.concatenate([[np.nan], otp[:-1]]), np.concatenate([[np.nan], asp[:-1]])
        df["YoY ASP productivity %"] = np.where((asp_prev > 0) & (asp > 0), (asp - asp_prev) / asp_prev * 100, np.nan)
        df["YoY OTP productivity %"] = np.where((otp_prev > 0) & (otp > 0), (otp - otp_prev) / otp_prev * 100, np.nan)
        savings = np.where((otp_prev > 0) & (otp > 0), (otp - otp_prev) * vol, 0.0)
    df["Project savings (OTP change x volume)"] = savings
    df["Cumulative FCF"] = np.cumsum(fcf)

    excel = P["excel_npv"]
    irr = compute_irr(list(fcf))
    payback = compute_payback(fcf)
    disc = np.array([cf / (1 + rate) ** (i + (1 if excel else 0)) for i, cf in enumerate(fcf)])
    tot_nr = total_nr.sum()
    capex_total = out["CapEx"].sum()
    rde_net_total = out["RD&E net"].sum()
    qs_paid_total = -out["- Quicksavings paid"].sum()
    total_investment = capex_total + max(rde_net_total, 0) + qs_paid_total
    cm = out["Contribution margin"]
    cm_pct = df["Contribution margin %"].to_numpy()
    return {
        "df": df, "npv": npv, "irr": irr, "payback": payback,
        "payback_launch": (payback - L) if payback is not None else None,
        "disc_payback": compute_payback(disc), "total_nr": tot_nr, "total_volume": vol.sum(),
        "total_fcf": fcf.sum(), "total_cm": cm.sum(),
        "avg_cm_pct": cm.sum() / tot_nr * 100 if tot_nr else 0.0,
        "avg_gm_pct": out["Gross (make) margin"].sum() / tot_nr * 100 if tot_nr else 0.0,
        "peak_cm_pct": float(np.nanmax(cm_pct[selling])) if selling.any() else 0.0,
        "total_investment": total_investment,
        "roi": fcf.sum() / total_investment if total_investment > 0 else None,
        # Company Excel: NPD Effectiveness = Net revenue Yr1-Yr5 / Program specific RD&E (total);
        #                Return on RD&E  = EBIT Yr1-Yr5 / Program specific RD&E (total)
        "nr_y15": (nr_y15 := float(total_nr[:5].sum())),
        "ebit_y15": (ebit_y15 := float(cm[:5].sum())),
        "rde_program": (rde_prog := float(out["RD&E net"].sum()) if P["rde_net_of_nre"]
                        else float((out["RD&E labour"] + out["RD&E expenses"]).sum())),
        "npd_eff": nr_y15 / rde_prog if rde_prog > 0 else None,
        "return_on_rde": ebit_y15 / rde_prog if rde_prog > 0 else None,
        "total_savings": savings.sum(),
        "peak_i": (peak_i := int(np.argmax(np.where(selling, total_nr, -np.inf)))) if selling.any() else None,
        "peak_year": years[peak_i] if selling.any() else None,
        "peak_rev": float(total_nr[peak_i]) if selling.any() else 0.0,
        "peak_gm": float(out["Gross (make) margin"][peak_i]) if selling.any() else 0.0,
        "peak_gm_pct": float(out["Gross (make) margin"][peak_i] / total_nr[peak_i] * 100)
        if selling.any() and total_nr[peak_i] else 0.0,
    }


def with_price(P, price):
    """Copy of the inputs with another quoted selling price (used for the price-scenario comparison)."""
    P2 = dict(P)
    P2["asp_all"] = price
    launch_price = price_path(P, price)[0] if P["price_down"] else price
    P2["products"] = {pk: dict(v, asp=launch_price) for pk, v in P["products"].items()}
    return P2


def run_set(P, factors, full=True, rate_delta=0.0, **kw):
    runs = [run_product(P, pk, f, **kw) for pk, f in factors.items()]
    return combine(runs, P, rate_delta, full)


def evaluate(P, view, full=True, rate_delta=0.0, **kw):
    """Combined case, or one product carrying its volume share of the shared costs (allocated view)."""
    shares = lifetime_shares(P, PKEYS)
    factors = shares if view == COMBINED else {VIEW_KEY[view]: shares[VIEW_KEY[view]]}
    return run_set(P, factors, full, rate_delta, **kw)


def run_model(P, **kw):
    """Kept for compatibility with the original single-case code: evaluates the selected view."""
    return evaluate(P, VIEW, **kw)


def unit_landed(P, pk, market, stage="steady"):
    """Pending cost + what Sensata pays for freight, insurance and duty for one unit to one market, at launch ASP.
    stage 'steady' = after the learning curve, 'launch' = launch-year CLAM premium."""
    b, prem, _ = product_cost_base(P, pk)
    mat = b["mat"] + b["moh"]
    clam = (b["dl"] + b["oh"]) * (prem if stage == "launch" else 1.0)
    asp = P["products"][pk]["asp"]
    leg = fg_leg(P, pk, market, asp, mat + clam)
    return dict(material=mat, clam=clam, freight=leg["freight"], insurance=leg["insurance"], rate=leg["rate"],
                cv=leg["cv"], duty=leg["duty"], duty_payer=leg["duty_payer"], lane_freight=leg["lane_freight"],
                landed=mat + clam + leg["freight"] + leg["insurance"] + leg["duty"], asp=asp)


def statement(df, rows, pct_rows=(), unit_rows=()):
    """Excel-style layout: metrics as rows, years as columns, plus a total column."""
    t = df.set_index("Year")[rows].T
    sum_rows = [r for r in rows if r not in pct_rows and r not in unit_rows and not r.startswith("Cumulative")]
    t["Total"] = np.nan
    t.loc[sum_rows, "Total"] = t.loc[sum_rows].drop(columns="Total").sum(axis=1)
    sty = t.style.format("{:,.0f}", na_rep="")
    if pct_rows:
        sty = sty.format("{:.1f}%", subset=pd.IndexSlice[list(pct_rows), :], na_rep="")
    if unit_rows:
        sty = sty.format("{:,.2f}", subset=pd.IndexSlice[list(unit_rows), :], na_rep="")
    return sty


# =====================================================
# MAIN PAGE – QUICK LEVERS
# =====================================================
from contextlib import contextmanager

st.title("EZ Sensor Pro 2.4GHz – business case")
st.caption("Make site AGM (Mexico) → distribution centres Fort Worth (USA) and Bergkirchen (Germany). "
           "Products: HSSI EU (10°), HSSI NA (20°), Gamma NA/EU. Money in $k, volumes in k units.")

cb = st.columns([2.0, 1.6, 1.4, 1.4, 1.0])
VIEW = cb[0].selectbox("View", VIEWS,
                       help="Combined = the 3 products as one business case. A product view = that product with "
                            "its volume share of the shared costs.")
PRICE = cb[1].radio("Selling price", ["A", "B"], horizontal=True, key="price_main",
                    format_func=lambda x: f"{x}: {P['price_' + x]:.2f} $",
                    help="The two price scenarios (sidebar → Selling price). The Decision tab always compares both.")
wi_vol = cb[2].slider("What-if: volume %", -50, 50, 0, 5, help="Moves the whole volume forecast up or down.")
wi_mat = cb[3].slider("What-if: material cost %", -30, 30, 0, 5, help="Moves the material cost (MAT + MOH) up or down.")
PRESENTER = cb[4].toggle("Presenter mode", value=False,
                         help="Hides the guides, step-by-step calculations and the takeaways outside the Decision tab.")
SHOW_DETAILS = not PRESENTER

P = with_price(P, P["price_" + PRICE])
P["price_scen"] = PRICE
P["whatif_vol"], P["whatif_mat"] = 1 + wi_vol / 100, 1 + wi_mat / 100
if wi_vol or wi_mat:
    st.info(f"What-if active: volume {wi_vol:+d}%, material cost {wi_mat:+d}%. Every tab includes it.")


def show_guide(key, title_key="tab"):          # overrides the version above: hidden in presenter mode
    if SHOW_DETAILS:
        with st.expander(GUIDE_TITLES[title_key]):
            st.markdown(GUIDE[key])


@contextmanager
def details(label):
    """Expander with the step-by-step calculations; hidden in presenter mode."""
    if SHOW_DETAILS:
        with st.expander(label):
            yield
    else:
        ph = st.empty()
        with ph.container():
            yield
        ph.empty()


def takeaway(section, level, title, argument, action):   # overrides the version above
    icon, box = _LEVEL[level]
    TAKEAWAYS.append(dict(Section=section, Level=f"{icon} {level}", Conclusion=title, Argument=argument, Action=action))
    if SHOW_DETAILS or section == "Decision":
        box(f"**{title}**\n\n{argument}\n\n**Action:** {action}")


GUIDE.update({
    "overview": """
**What this model does.** It evaluates the EZ Sensor Pro project (3 products, made in AGM, sold through the DCs in Fort Worth and Bergkirchen) the same way the company Cash Flow Excel does, and shows whether it is worth investing in.

**How the numbers flow (same order as the Excel)**
1. **Revenue** = volume × selling price (price A or B, with the price-down), plus samples, CUF and quicksavings.
2. **Unit cost (OTP)** = material (MAT ÷ yield + MOH) + CLAM (labour + overhead + depreciation) + freight and duties to the DC.
3. **Gross (make) margin** = revenue − all cost of goods sold (incl. outbound freight, warehouse, COPQ).
4. **Contribution margin** = gross margin − RD&E − SG&A − cost of payment terms.
5. **Free cash flow** = contribution margin + non-cash items − CapEx − change in working capital.
6. **NPV, IRR, payback, NPD Effectiveness, Return on RD&E** give the go / no-go answer against the hurdles.

**How to use it.** The quick levers are on top of the page: view (combined or one product), price A or B, what-if on volume and material, and presenter mode. All detailed inputs are in the sidebar, grouped in the same order as the Excel. The **Explain** tab says where every input comes from.
""",
    "decision": """
The one-page answer: is the project worth doing, and at which price?

- **Top row** – the key results of the case on the screen (view, price and what-if chosen above).
- **Investment decision** – the same table as in the company Excel. 🟢 hurdle met, 🔴 not met, ⚪ no hurdle.
  - **NPV** at the WACC must be above 0: all yearly free cash flows converted to today's money.
  - **Manufacturing margin** (gross margin ÷ revenue over the horizon) must beat each benchmark.
  - **Payback** – years from the project start until the cumulative cash turns positive; must be under the hurdle.
  - **Accretion / (dilution)** = (margin of the year with the highest revenue − benchmark) × revenue of that year.
  - **NPD Effectiveness** = revenue of years 1–5 ÷ program-specific RD&E. **Return on RD&E** = EBIT of years 1–5 ÷ program-specific RD&E.
- **Price A vs price B** – both scenarios side by side, whatever is selected above, plus the lowest price that still meets all hurdles.
""",
    "pl_excel": """
The P&L in the same order as the company Excel (sheet *1. P&L*): revenue → material → factory (CLAM) → freight & duties → overhead COGS → gross (make) margin → RD&E → SG&A → payment terms → contribution margin.

- **Total material** = raw material (MAT, adjusted for yield) + material overhead (MOH = inbound freight and duties of the components).
- **Total factory** = CLAM (direct labour RES + indirect labour & overhead OH) + depreciation of the new investment.
- **Freight & duties (MS→DC)** = transport from AGM and the import duty on the finished product, where Sensata pays them.
- **Overhead COGS** = outbound freight (DC → customer), warehouse and COPQ, each a % of item revenue.
- **Gross (make) margin** = total revenue − total COGS.
- **RD&E nett** = labour + expenditures − NRE paid by the customer.
- **Contribution margin** = gross margin − RD&E nett − SG&A − cost of payment terms.

Switch on **% of revenue** to see every line as a share of total revenue, like the % columns in the Excel.
""",
    "cf_excel": """
The cash flow in the same logic as the company Excel (sheet *2. Cashflow model*): start from the contribution margin, add back what is not cash, take off the investment and the cash tied up in working capital.

- **+ Cost of payment terms** and **+ depreciation** are costs in the P&L but not payments, so they are added back.
- **− Capital expenditures** – the cash paid for the new equipment (sidebar → Additional investment).
- **Quicksavings** – the P&L spreads the price concession over the years; in cash it is paid at once.
- **− Change in working capital** – receivables (DSO) + inventory (DIO) − payables (DPO). Growth ties up cash; at the end it comes back.
- **Payback** = years from the project start until the cumulative FCF turns positive (full years, like the Excel).
- **NPV** uses the Excel NPV() convention: the first year is discounted by one full year.
""",
    "unitcost": """
What one unit costs, by product, and how the unit cost of the case moves over the years.

- The cost table in the sidebar is **pre-filled with the pending costs** of the Item Readiness Report (AGM) and can be edited by hand.
- **MAT** = parts cost; **MOH** = duty and freight of the components to Sensata; **RES** = direct labour; **OH** = indirect labour and other overhead. **Conversion = RES + OH.**
- **OTP** (unit cost) = material + CLAM + freight + insurance + finished-goods duty. The dotted line is the selling price; the gap is the margin per unit.
- Gamma is still in ramp-up in AGM (its conversion is ~10× HSSI); the model brings it down to the HSSI level over the years set in the sidebar.
""",
    "explain": """
Where every input comes from and how this model follows the company Cash Flow Excel.

- **Data register** – every input with its value, its source, the owner (as in the Excel *Data Register*) and its status: ✅ confirmed, 🟡 assumption, 🔴 placeholder to be replaced.
- **Company Excel vs this model** – line by line, what is the same and what is done differently, and why.
- **All takeaways** – every conclusion of the other tabs, with the argument and the action.
- **Glossary** – the guide texts of all tabs in one place.
""",
})

show_guide("overview", "overview")
base = evaluate(P, VIEW)
df = base["df"]
years = df["Year"]
combined = evaluate(P, COMBINED) if VIEW != COMBINED else base
view_tag = "combined case" if VIEW == COMBINED else f"{VIEW} (allocated)"

tabs = st.tabs(["Decision", "P&L", "Cash flow", "Unit cost & products", "Tariffs & logistics",
                "One case or three?", "Risk", "Explain"])


def acc_fmt(x):
    return f"{x:,.0f}" if x >= 0 else f"({-x:,.0f})"


def light(ok):
    return "⚪" if ok is None else ("🟢" if ok else "🔴")


def excel_table(rows, cols, pct_of=None, bold=()):
    """rows = [(label, array, kind)]; kind: 'sum' (money), 'avg' (unit value), 'pct' (share), 'vol'.
    Returns a Styler with the years as columns and a Total column, like the company Excel."""
    data, fmt_rows = {}, {}
    for label, arr, kind in rows:
        arr = np.asarray(arr, dtype=float)
        if pct_of is not None and kind == "sum":
            with np.errstate(divide="ignore", invalid="ignore"):
                vals = np.where(pct_of != 0, arr / pct_of * 100, np.nan)
            tot = arr.sum() / pct_of.sum() * 100 if pct_of.sum() else np.nan
            fmt_rows[label] = "{:.1f}%"
        else:
            vals = arr
            if kind in ("sum", "vol"):
                tot = arr.sum()
            elif kind == "last":
                tot = np.nan
            elif kind == "avg":
                nz = arr[arr != 0]
                tot = nz.mean() if len(nz) else np.nan
            else:
                tot = np.nan
            fmt_rows[label] = {"sum": "{:,.0f}", "vol": "{:,.1f}", "avg": "{:,.2f}", "pct": "{:.1f}%", "last": "{:,.0f}"}[kind]
        data[label] = list(vals) + [tot]
    t = pd.DataFrame(data, index=list(cols) + ["Total"]).T
    sty = t.style
    for label, f in fmt_rows.items():
        sty = sty.format(f, subset=pd.IndexSlice[[label], :], na_rep="")
    sty = sty.apply(lambda r: ["font-weight: bold" if r.name in bold else "" for _ in r], axis=1)
    return sty


# ---------- 1. DECISION ----------
with tabs[0]:
    show_guide("decision")
    st.subheader(f"Decision – {view_tag}, price {PRICE} ({P['asp_all']:.2f} $/unit)")
    c = st.columns(6)
    c[0].metric("NPV ($k)", k(base["npv"]), help=f"At {P['wacc'] * 100:.0f}% WACC.")
    c[0].caption("All future cash converted to today's value. > 0 = the project earns more than the required return.")
    c[1].metric("IRR", pct(base["irr"]))
    c[1].caption("The project's yearly return. Must be above the WACC for the investment to be worth it.")
    c[2].metric("Payback", years_fmt(base["payback"], " yrs"))
    c[2].caption("After how many years the money invested in the project comes back.")
    c[3].metric("Manufacturing margin", f"{base['avg_gm_pct']:.1f}%")
    c[3].caption("Gross margin ÷ revenue over the whole horizon. Compared against the business-unit benchmarks.")
    c[4].metric("NPD Effectiveness", f"{base['npd_eff']:.1f}" if base["npd_eff"] else "n/a")
    c[4].caption("Revenue years 1–5 ÷ RD&E. How many $ of revenue each $ of RD&E spend generates.")
    c[5].metric("Return on RD&E", f"{base['return_on_rde']:.1f}" if base["return_on_rde"] else "n/a")
    c[5].caption("EBIT years 1–5 ÷ RD&E. How many $ of profit each $ of RD&E spend generates.")

    st.divider()
    st.markdown("**🎛️ Try your own price**")
    tp_col1, tp_col2 = st.columns([2, 3])
    try_price = tp_col1.slider("Test price ($/unit)", 5.0, 20.0,
                               float(P["asp_all"]), 0.1, key="try_price_slider",
                               help="Move the slider to see instantly whether the project meets the hurdles at this price. "
                                    "Does not change the price A/B selected above.")
    try_res = evaluate(with_price(P, try_price), VIEW)
    try_tests = [try_res["npv"] > 0] + [try_res["avg_gm_pct"] > h for _, h in P["mm_hurdles"]] \
        + [try_res["payback"] is not None and try_res["payback"] < P["payback_hurdle"]]
    with tp_col2:
        tc = st.columns(4)
        tc[0].metric("NPV at this price", k(try_res["npv"]), delta=k(try_res["npv"] - base["npv"]))
        tc[1].metric("Manufacturing margin", f"{try_res['avg_gm_pct']:.1f}%",
                    delta=f"{try_res['avg_gm_pct'] - base['avg_gm_pct']:+.1f} pp")
        tc[2].metric("Payback", years_fmt(try_res["payback"], " yrs"))
        tc[3].metric("Hurdles met", f"{sum(try_tests)} / {len(try_tests)}")
    lights_row = " ".join(light(ok) for ok in try_tests)
    st.caption(f"{lights_row}  (NPV, " + ", ".join(n for n, _ in P["mm_hurdles"]) + ", Payback)")
    st.divider()

    wacc_pct = P["wacc"] * 100
    avg_mm = base["avg_gm_pct"]
    tests = [("NPV", base["npv"] > 0)]
    dec = [{"Investment decision": f"NPV @ {wacc_pct:.1f}%", "Value": k(base["npv"]), "Hurdle rate": "> $0.00",
            "Explanation": light(base["npv"] > 0), "Accretion/(Dilution) year with highest rev.": ""}]
    for name, h in P["mm_hurdles"]:
        ok = avg_mm > h
        tests.append((f"Manufacturing margin {name}", ok))
        dec.append({"Investment decision": f"Manufacturing Margin {name}", "Value": f"{avg_mm:.1f}%",
                    "Hurdle rate": f"> {h:.1f}%", "Explanation": light(ok),
                    "Accretion/(Dilution) year with highest rev.": acc_fmt((base["peak_gm_pct"] - h) / 100 * base["peak_rev"])})
    pb_ok = base["payback"] is not None and base["payback"] < P["payback_hurdle"]
    tests.append(("Payback", pb_ok))
    dec.append({"Investment decision": "Payback Years", "Value": years_fmt(base["payback"]),
                "Hurdle rate": f"< {P['payback_hurdle']} years", "Explanation": light(pb_ok),
                "Accretion/(Dilution) year with highest rev.": ""})
    dec.append({"Investment decision": "NPD Effectiveness", "Value": f"{base['npd_eff']:.1f}" if base["npd_eff"] else "n/a",
                "Hurdle rate": "", "Explanation": light(None), "Accretion/(Dilution) year with highest rev.": ""})
    dec.append({"Investment decision": "Return on RD&E",
                "Value": f"{base['return_on_rde']:.1f}" if base["return_on_rde"] else "n/a", "Hurdle rate": "",
                "Explanation": light(None), "Accretion/(Dilution) year with highest rev.": ""})

    left, right = st.columns([1.25, 1])
    with left:
        st.markdown("**Investment decision**")
        st.dataframe(pd.DataFrame(dec), hide_index=True, column_config={
            "Value": st.column_config.TextColumn(help="Текущата стойност на метриката в нашия модел, при избраните допускания."),
            "Hurdle rate": st.column_config.TextColumn(help="Минималният праг, зададен от Финанси, за да мине проектът."),
            "Explanation": st.column_config.TextColumn(help="🟢 = meets the hurdle, 🔴 = does not meet it, ⚪ = no hurdle set for this metric."),
            "Accretion/(Dilution) year with highest rev.": st.column_config.TextColumn(
                help="(peak-year margin − benchmark) × peak-year revenue. Positive = raises the business unit's average margin; in brackets = dilutes it."),
        })
        st.caption(f"Year with the highest revenue: {base['peak_year']} ({k(base['peak_rev'])} $k, margin "
                   f"{base['peak_gm_pct']:.1f}%).")
        with st.popover("❓ What am I looking at here"):
            st.markdown("""
- **NPV** – whether the project earns more than the required return (WACC), in absolute $.
- **Manufacturing Margin** (x3 rows) – the product's margin against the three business benchmarks: Tire Management Solutions, TPMS, Sensata Worldwide. Each is a separate test.
- **Payback Years** – usually the toughest test: how fast the money comes back.
- **NPD/RoRD&E** – informational, no hurdle, but show how effective the RD&E investment is.
""")

    # --- price A vs price B ---
    top_h = max([h for _, h in P["mm_hurdles"]], default=0.0)

    def hurdles_ok(r_):
        return (r_["npv"] > 0 and all(r_["avg_gm_pct"] > h for _, h in P["mm_hurdles"])
                and r_["payback"] is not None and r_["payback"] < P["payback_hurdle"])

    def min_price(test, lo=0.0, hi=100.0):
        if not test(evaluate(with_price(P, hi), VIEW)):
            return None
        for _ in range(20):
            mid = (lo + hi) / 2
            lo, hi = (lo, mid) if test(evaluate(with_price(P, mid), VIEW)) else (mid, hi)
        return hi

    ps_res, ps_rows = {}, []
    for lbl in ("A", "B"):
        pr = P["price_" + lbl]
        r_ = evaluate(with_price(P, pr), VIEW)
        ps_res[lbl] = r_
        n_ok = sum([r_["npv"] > 0, r_["payback"] is not None and r_["payback"] < P["payback_hurdle"]]
                   + [r_["avg_gm_pct"] > h for _, h in P["mm_hurdles"]])
        ps_rows.append({"": f"Price {lbl}" + (" ◀" if lbl == PRICE else ""), "Quoted $/unit": f"{pr:.2f}",
                        "NPV ($k)": k(r_["npv"]), "IRR": pct(r_["irr"]), "Payback": years_fmt(r_["payback"]),
                        "Margin": f"{r_['avg_gm_pct']:.1f}%", "Hurdles met": f"{n_ok} / {2 + len(P['mm_hurdles'])}"})
    p_all = min_price(hurdles_ok)
    with right:
        st.markdown("**Price A vs price B**")
        st.dataframe(pd.DataFrame(ps_rows), hide_index=True, column_config={
            "Hurdles met": st.column_config.TextColumn(help="Number of hurdles met out of the total: NPV + every margin benchmark + payback.")})
        fig = go.Figure()
        for lbl in ("A", "B"):
            fig.add_scatter(x=years, y=ps_res[lbl]["df"]["Cumulative FCF"], mode="lines+markers",
                            name=f"Price {lbl} ({P['price_' + lbl]:.2f} $)")
        fig.add_hline(y=0, line_dash="dash", line_color="gray",
                     annotation_text="Payback point (cumulative flow crosses 0)", annotation_font_size=9)
        fig.update_layout(title="Cumulative free cash flow ($k)", height=300, margin=dict(t=40, b=10))
        st.plotly_chart(fig)
        st.caption("Lowest quoted price that meets every hurdle: "
                   + (f"**{p_all:.2f} $/unit**" if p_all is not None else "not reached below 100 $/unit") + ".")

    with details("Step-by-step calculations"):
        pth_ = price_path(P, P["asp_all"])
        st.markdown(f"- Price {PRICE}: quoted {P['asp_all']:.2f} $/unit, price-down per year: " + "; ".join(
            f"{y}: {P['price_down'][j] * 100:.1f}% → {pth_[j]:.4f}"
            for j, y in enumerate(years[P['launch']:P['launch'] + len(pth_)])))
        st.markdown(f"- Manufacturing margin = gross margin {k(df['Gross (make) margin'].sum())} ÷ revenue "
                    f"{k(base['total_nr'])} = **{avg_mm:.2f}%**")
        st.markdown(f"- Year with the highest revenue {base['peak_year']}: {k(base['peak_gm'])} ÷ {k(base['peak_rev'])} = "
                    f"**{base['peak_gm_pct']:.2f}%**; accretion = (margin − benchmark) × {k(base['peak_rev'])}")
        y15 = ", ".join(years[:5])
        st.markdown(f"- Years 1–5 = {y15}. Revenue Yr1–5 = " + " + ".join(k(v) for v in df["Total net revenue"][:5])
                    + f" = **{k(base['nr_y15'])}** $k; EBIT Yr1–5 = " + " + ".join(acc_fmt(v) for v in df["Contribution margin"][:5])
                    + f" = **{acc_fmt(base['ebit_y15'])}** $k")
        if base["npd_eff"]:
            st.markdown(f"- NPD Effectiveness = {k(base['nr_y15'])} ÷ RD&E {k(base['rde_program'])} = **{base['npd_eff']:.1f}**; "
                        f"Return on RD&E = {acc_fmt(base['ebit_y15'])} ÷ {k(base['rde_program'])} = **{base['return_on_rde']:.1f}**")
        cum = df["Cumulative FCF"].to_numpy()
        neg = np.where(cum < 0)[0]
        if base["payback"] is not None and len(neg):
            j = neg[-1]
            st.markdown(f"- Payback = {j + 1} full year(s) + {k(-cum[j])} ÷ {k(df['Free cash flow'].iloc[j + 1])} = "
                        f"**{base['payback']:.2f}** years")

    st.markdown("**Key takeaways**")
    failed = [t[0] for t in tests if not t[1]]
    if not failed:
        takeaway("Decision", "ok", f"All {len(tests)} hurdles are met at price {PRICE}",
                 f"NPV {k(base['npv'])} $k, margin {avg_mm:.1f}% vs the highest benchmark {top_h:.1f}%, payback "
                 f"{years_fmt(base['payback'], ' yrs')} vs < {P['payback_hurdle']} yrs.",
                 "Go, subject to the open inputs in the Explain tab.")
    else:
        takeaway("Decision", "risk", f"{len(failed)} of {len(tests)} hurdles failed at price {PRICE}",
                 "Failed: " + ", ".join(failed) + f". NPV {k(base['npv'])} $k, margin {avg_mm:.1f}%, payback "
                 f"{years_fmt(base['payback'], ' yrs')}.",
                 "See which lever closes the gap in the Risk tab (tornado).")
    ra, rb = ps_res["A"], ps_res["B"]
    lvl = "ok" if hurdles_ok(ra) else ("warn" if hurdles_ok(rb) else "risk")
    takeaway("Decision", lvl, f"Price A {P['price_A']:.2f} $ vs price B {P['price_B']:.2f} $",
             f"NPV {k(ra['npv'])} vs {k(rb['npv'])} $k; margin {ra['avg_gm_pct']:.1f}% vs {rb['avg_gm_pct']:.1f}%; "
             f"payback {years_fmt(ra['payback'], ' yrs')} vs {years_fmt(rb['payback'], ' yrs')}. Lowest price for all "
             "hurdles: " + (f"{p_all:.2f} $." if p_all is not None else "not reached."),
             "Both prices meet all hurdles." if hurdles_ok(ra) else
             (("Only price B meets all hurdles: do not go below " + (f"{p_all:.2f}" if p_all else "price B") + " $.")
              if hurdles_ok(rb) else "Neither price meets all hurdles: reduce cost or renegotiate before go."))


# ---------- 2. P&L ----------
with tabs[1]:
    show_guide("pl_excel")
    st.subheader(f"P&L ($k) – {view_tag}, price {PRICE}")
    as_pct = st.toggle("Show as % of total revenue", value=False)
    vol = df["Volume (k units)"].to_numpy()
    tnr = df["Total net revenue"].to_numpy()
    mat_y = df["Material, yielded ($/unit)"].to_numpy() * vol
    moh = df["Material overhead MOH ($/unit)"].to_numpy() * vol
    adddep = df["+ Additional investment depreciation"].to_numpy()
    frt = (df["Freight MS→DC"] + df["Cargo insurance"]).to_numpy()
    fgd = df["Finished-goods duties"].to_numpy()
    rows = [
        ("Volume (k units)", vol, "vol"), ("ASP ($/unit)", df["ASP ($/unit)"], "avg"),
        ("Item revenue", df["Item net revenue"], "sum"),
        ("Non-item revenue (samples, CUF, quicksavings)",
         df["Sample net revenue"] + df["CUF"] + df["Quicksavings amortization"], "sum"),
        ("Total revenue", tnr, "sum"),
        ("Raw material (MAT, yielded)", mat_y, "sum"), ("Yield %", df["Yield %"], "avg"),
        ("Material overhead – inbound freight & duties (MOH)", moh, "sum"), ("Total material", df["Material"], "sum"),
        ("CLAM (labour & overhead)", df["CLAM"].to_numpy() - adddep, "sum"),
        ("Additional investment depreciation", adddep, "sum"), ("Total factory", df["CLAM"], "sum"),
        ("Freight AGM → DC (incl. insurance)", frt, "sum"), ("Finished-goods duties", fgd, "sum"),
        ("Total freight & duties (MS→DC)", frt + fgd, "sum"),
        ("Outbound freight (DC → customer)", df["Outbound freight"], "sum"), ("Warehouse", df["Warehouse"], "sum"),
        ("COPQ (warranty)", df["COPQ (warranty)"], "sum"), ("Total overhead COGS", df["Overhead COGS"], "sum"),
        ("Total COGS", df["Total COGS"], "sum"), ("Gross margin / Make margin", df["Gross (make) margin"], "sum"),
        ("RD&E labour", df["RD&E labour"], "sum"), ("RD&E expenditures", df["RD&E expenses"], "sum"),
        ("NRE (paid by the customer)", df["NRE (customer funded)"], "sum"), ("RD&E nett", df["RD&E net"], "sum"),
        ("SG&A", df["SG&A"], "sum"), ("Cost of payment terms", df["Cost of payment terms"], "sum"),
        ("Contribution margin / Operating income", df["Contribution margin"], "sum"),
    ]
    bold = {"Total revenue", "Total material", "Total factory", "Total freight & duties (MS→DC)", "Total overhead COGS",
            "Total COGS", "Gross margin / Make margin", "RD&E nett", "Contribution margin / Operating income"}

    c1, c2 = st.columns(2)
    with c1:
        if VIEW == COMBINED:
            vs = pd.DataFrame({"Year": years})
            for pk in PKEYS:
                vs[PNAME[pk]] = run_product(P, pk, 0)["Volume (k units)"]
            st.plotly_chart(px.bar(vs, x="Year", y=[PNAME[pk] for pk in PKEYS], title="Volume by product (k units)",
                                   height=280))
        else:
            fig = go.Figure()
            fig.add_bar(x=years, y=df["Total net revenue"], name="Revenue")
            fig.add_bar(x=years, y=df["Total COGS"], name="COGS")
            fig.add_scatter(x=years, y=df["Gross (make) margin"], name="Gross margin", mode="lines+markers")
            fig.update_layout(barmode="group", title="Revenue, COGS & gross margin ($k)", height=280)
            st.plotly_chart(fig)
    with c2:
        mdf = df[df["Total net revenue"] != 0]
        fig = go.Figure()
        fig.add_scatter(x=mdf["Year"], y=mdf["Gross (make) margin"] / mdf["Total net revenue"] * 100, name="Gross margin %",
                        mode="lines+markers")
        fig.add_scatter(x=mdf["Year"], y=mdf["Contribution margin"] / mdf["Total net revenue"] * 100,
                        name="Contribution margin %", mode="lines+markers")
        for name, h in P["mm_hurdles"]:
            fig.add_hline(y=h, line_dash="dot", line_color="gray", annotation_text=name, annotation_font_size=9)
        fig.update_layout(title="Margins vs benchmarks (%)", height=280)
        st.plotly_chart(fig)

    st.markdown("**Full P&L (as in the Excel)**")
    st.dataframe(excel_table(rows, years, pct_of=tnr if as_pct else None, bold=bold), height=560)

    with details("Annual metrics summary (as in the Excel)"):
        st.dataframe(statement(df, ["Volume (k units)", "ASP ($/unit)", "YoY ASP productivity %",
                                    "OTP / unit cost ($/unit)", "YoY OTP productivity %",
                                    "Project savings (OTP change x volume)", "Gross (make) margin", "Gross margin %",
                                    "Contribution margin", "Contribution margin %"],
                               pct_rows=["YoY ASP productivity %", "YoY OTP productivity %", "Gross margin %",
                                         "Contribution margin %"],
                               unit_rows=["ASP ($/unit)", "OTP / unit cost ($/unit)"]))

    st.markdown("**Takeaways**")
    duties_total = df["Finished-goods duties"].sum()
    takeaway("P&L", "info", f"Material is {df['Material'].sum() / df['Total COGS'].sum() * 100:.0f}% of COGS; "
                            f"duties {duties_total / df['Total COGS'].sum() * 100:.0f}%",
             f"Total material {k(df['Material'].sum())} $k, factory {k(df['CLAM'].sum())} $k, freight & duties "
             f"{k((frt + fgd).sum())} $k, overhead COGS {k(df['Overhead COGS'].sum())} $k of total COGS "
             f"{k(df['Total COGS'].sum())} $k.",
             "Cost-down effort goes to material and duty (origin) first; labour is a small lever.")


# ---------- 3. CASH FLOW ----------
with tabs[2]:
    show_guide("cf_excel")
    st.subheader(f"Free cash flow ($k) – {view_tag}, price {PRICE}")
    cf_all = [
        ("Contribution margin", df["Contribution margin"], "sum"),
        ("− Income tax", df["Income tax"], "sum"),
        ("+ Cost of payment terms (not a payment)", df["+ Cost of payment terms (non-cash)"], "sum"),
        ("+ Depreciation, standard make", df["+ Standard make depreciation"], "sum"),
        ("+ Depreciation, additional investment", df["+ Additional investment depreciation"], "sum"),
        ("+ Quicksavings amortization (P&L only)", df["+ Quicksavings amortization"], "sum"),
        ("− Quicksavings paid", df["- Quicksavings paid"], "sum"),
        ("− Capital expenditures", df["- Capital expenditures"], "sum"),
        ("− Change in working capital", df["- Change in working capital"], "sum"),
        ("+ Working capital release", df["+ Working capital release"], "sum"),
        ("Free cash flow", df["Free cash flow"], "sum"),
    ]
    cf_rows = [r for r in cf_all if np.abs(np.asarray(r[1], dtype=float)).sum() > 0
               or r[0] in ("Contribution margin", "Free cash flow")]
    cf_rows.append(("Cumulative FCF", df["Cumulative FCF"], "last"))

    c = st.columns(4)
    c[0].metric("NPV ($k)", k(base["npv"]))
    c[1].metric("IRR", pct(base["irr"]))
    c[2].metric("Payback", years_fmt(base["payback"], " yrs"))
    c[3].metric("Discounted payback", years_fmt(base["disc_payback"], " yrs"))

    fig = go.Figure()
    fig.add_bar(x=years, y=df["Free cash flow"], name="Free cash flow")
    fig.add_scatter(x=years, y=df["Cumulative FCF"], name="Cumulative FCF", mode="lines+markers")
    fig.add_hline(y=0, line_dash="dash", line_color="gray",
                 annotation_text="Payback point", annotation_font_size=9)
    fig.update_layout(title="Free cash flow and payback ($k)", height=330)
    st.plotly_chart(fig)

    st.markdown("**Full cash flow bridge (as in the Excel)**")
    st.dataframe(excel_table(cf_rows, years, bold={"Free cash flow", "Contribution margin"}))

    with details("Working capital detail (DSO, DIO, DPO)"):
        st.dataframe(excel_table([("Receivables (DSO)", df["Receivables (DSO)"], "avg"),
                                  ("Inventory (DIO)", df["Inventory (DIO)"], "avg"),
                                  ("Payables (DPO)", df["Payables (DPO)"], "avg"),
                                  ("Net working capital", df["Working capital"], "avg")], years,
                                 bold={"Net working capital"}))
        st.caption(f"Receivables = {P['dso']}/365 × item revenue; inventory = {P['dio']}/365 × product COGS (cash); "
                   f"payables = {P['dpo']}/365 × material. The Total column shows the average.")

    st.markdown("**Takeaways**")
    peak_i = int(df["Working capital"].idxmax())
    takeaway("Cash flow", "info", f"Working capital peaks at {k(df['Working capital'].max())} $k in {df['Year'][peak_i]}",
             f"DSO {P['dso']} + DIO {P['dio']} − DPO {P['dpo']} days tie up cash while the volume grows; it comes back "
             "at the end.",
             "Longer supplier terms (DPO) or lower stock (DIO) shorten the payback directly.")
    lvl = "ok" if base["payback"] is not None and base["payback"] < P["payback_hurdle"] else "warn"
    takeaway("Cash flow", lvl, f"Payback {years_fmt(base['payback'], ' yrs')} vs hurdle < {P['payback_hurdle']} yrs",
             f"Cumulative FCF turns positive after {years_fmt(base['payback'], ' years')} from the project start.",
             "Within the hurdle." if lvl == "ok" else "Phase the CapEx and RD&E closer to launch, or raise the price.")


# ---------- 4. UNIT COST & PRODUCTS ----------
with tabs[3]:
    show_guide("unitcost")
    st.subheader("Unit cost per product (AGM, pending cost)")

    def tot(c_):
        return c_["mat"] + c_["moh"] + c_["dl"] + c_["oh"]

    mc_rows = []
    for pk in PKEYS:
        c_ = P["costs"][pk]
        mc_rows.append({"Product": PNAME[pk], "Part number": PRODUCTS[pk]["pn"], "MAT": c_["mat"], "MOH": c_["moh"],
                        "RES": c_["dl"], "OH": c_["oh"], "Conversion (RES+OH)": c_["dl"] + c_["oh"], "Total": tot(c_),
                        "Source": ("edited by hand" if any(e.startswith(PNAME[pk]) for e in P["cost_edited"])
                                   else ("Item Readiness Report, pending" if P["cost_src"] else "manual entry"))})
    mcd = pd.DataFrame(mc_rows)
    st.dataframe(mcd.style.format({c: "{:.5f}" for c in ["MAT", "MOH", "RES", "OH", "Conversion (RES+OH)", "Total"]}),
                 hide_index=True)

    c1, c2 = st.columns(2)
    with c1:
        fig = go.Figure()
        for col, nm in [("MAT", "Material (MAT)"), ("MOH", "Material overhead (MOH)"), ("RES", "Direct labour (RES)"),
                        ("OH", "Overhead (OH)")]:
            fig.add_bar(x=mcd["Product"], y=mcd[col], name=nm)
        for lbl in ("A", "B"):
            fig.add_scatter(x=mcd["Product"], y=[price_path(P, P["price_" + lbl])[0]] * 3, mode="markers",
                            name=f"Launch price {lbl}", marker=dict(size=12, symbol="diamond"))
        fig.update_layout(barmode="stack", title="Pending cost vs launch price ($/unit)", height=340)
        st.plotly_chart(fig)
    with c2:
        comps = ["Material, yielded ($/unit)", "Material overhead MOH ($/unit)", "Direct labour ($/unit)",
                 "Indirect labour & overhead ($/unit)", "Depreciation standard make ($/unit)",
                 "Additional investment depreciation ($/unit)", "Freight MS→DC ($/unit)", "Cargo insurance ($/unit)",
                 "Finished-goods duties ($/unit)"]
        sdf = df[df["Volume (k units)"] > 0]
        fig = go.Figure()
        for comp in comps:
            if sdf[comp].abs().sum() > 0:
                fig.add_bar(x=sdf["Year"], y=sdf[comp], name=comp.replace(" ($/unit)", ""))
        fig.add_scatter(x=sdf["Year"], y=sdf["ASP ($/unit)"], name="Selling price", mode="lines+markers",
                        line=dict(color="black", dash="dot"))
        fig.update_layout(barmode="stack", title=f"Unit cost (OTP) over time – {view_tag}", height=340)
        st.plotly_chart(fig)

    with details("Step-by-step calculations"):
        for pk in PKEYS:
            c_ = P["costs"][pk]
            st.markdown(f"- {PNAME[pk]}: {c_['mat']:.5f} + {c_['moh']:.5f} + {c_['dl']:.5f} + {c_['oh']:.5f} = "
                        f"**{tot(c_):.5f}** $/unit; conversion {c_['dl']:.5f} + {c_['oh']:.5f} = **{c_['dl'] + c_['oh']:.5f}**")
        if len(sdf):
            r0 = sdf.iloc[0]
            st.markdown(f"- OTP {r0['Year']} = " + " + ".join(f"{r0[c]:.4f}" for c in comps)
                        + f" = **{r0['OTP / unit cost ($/unit)']:.4f}** $/unit")

    st.markdown("**Takeaways**")
    g, h, e = P["costs"]["GAMMA"], P["costs"]["HSSI_NA"], P["costs"]["HSSI_EU"]
    gc, hc = g["dl"] + g["oh"], h["dl"] + h["oh"]
    if P["cost_edited"]:
        takeaway("Unit cost", "info", "Some unit costs differ from the pending cost",
                 "Edited by hand: " + ", ".join(P["cost_edited"]) + ".",
                 "Note the source of each edited value (quote, estimate).")
    if hc > 0 and gc > 1.5 * hc:
        takeaway("Unit cost", "warn", "Gamma is not yet a mature process in AGM",
                 f"Gamma conversion {gc:.5f} vs HSSI {hc:.5f} $/unit in the same plant: {gc:.5f} ÷ {hc:.5f} = {gc / hc:.1f}×.",
                 (f"The model brings Gamma from {P['gamma_clam_launch']:.3f} to {P['gamma_clam_steady']:.3f} $/unit in "
                  f"{P['gamma_years']} years. Ask AGM for the Gamma overhead plan at full volume.") if P["gamma_ramp"] else
                 "Ramp-up is switched off: Gamma carries today's conversion cost for the whole horizon (conservative).")
    mat_share = (h["mat"] + h["moh"]) / tot(h) * 100 if tot(h) > 0 else 0.0
    if tot(h) > 0:
        takeaway("Unit cost", "info", f"Material is {mat_share:.0f}% of the unit cost",
                 f"HSSI NA: ({h['mat']:.5f} + {h['moh']:.5f}) ÷ {tot(h):.5f} = {mat_share:.1f}%.",
                 "Priority for Purchasing: component prices and component origin (origin also decides the USMCA duty).")
    if abs((e["dl"] + e["oh"]) - hc) < 1e-6:
        takeaway("Unit cost", "info", "HSSI EU and HSSI NA share the same process",
                 f"Same conversion {hc:.5f} $/unit; HSSI EU costs {tot(e) - tot(h):.5f} $/unit more, all in material.",
                 "Plan the two HSSI versions as one line in capacity and CapEx.")


# ---------- 3. TARIFFS & LANDED COST ----------
with tabs[4]:
    show_guide("tariffs")
    st.header("Duties, freight terms and landed cost (from AGM)")

    def patched(duty_patch=None, s232=None, route=None):
        P2 = dict(P)
        P2["duty"] = {ln: dict(v) for ln, v in P["duty"].items()}
        for ln, patch in (duty_patch or {}).items():
            P2["duty"][ln].update(patch)
        if s232 is not None:
            P2["s232"] = s232
        if route is not None:
            P2["route"] = dict(route)
        return P2

    def npv_with(duty_patch=None, s232=None, route=None):
        return evaluate(patched(duty_patch, s232, route), COMBINED, full=False)["npv"]

    lane_rows = []
    for lane in LANES:
        d = P["duty"][lane]
        lane_rows.append({"Lane": f"AGM → {'Fort Worth DC / USA' if lane[1] == 'US' else 'Bergkirchen DC / Europe'}",
                          "MFN %": d["mfn"] * 100,
                          "Extra %": (25.0 if (lane[1] == "US" and P["s232"]) else d["add"] * 100),
                          "Preferential origin": "yes (0%)" if d["pref"] else "no",
                          "Effective rate %": duty_rate(P, lane) * 100, "Freight $/kg": P["freight_kg"][lane]})
    lc1, lc2 = st.columns([1.3, 1])
    with lc1:
        st.dataframe(pd.DataFrame(lane_rows).style.format({"MFN %": "{:.1f}", "Extra %": "{:.1f}",
                                                           "Effective rate %": "{:.1f}", "Freight $/kg": "{:.2f}"}),
                     hide_index=True)
    with lc2:
        ldf0 = pd.DataFrame(lane_rows)
        fig = go.Figure()
        fig.add_bar(x=ldf0["Lane"], y=ldf0["Effective rate %"], name="Effective duty rate %")
        fig.update_layout(title="Effective duty rate by lane (%)", height=260, margin=dict(t=40, b=10))
        st.plotly_chart(fig)

    st.subheader("Freight terms: who pays what")
    tr = []
    for m in ["US", "EU"]:
        rt, tname = P["route"][m], term_of(P, m)
        t = INCOTERMS[tname]
        tr.append({"Market": MARKETS[m], "Sales route": ROUTE_NAME[rt],
                   "Leg under the terms": "Sensata DC → customer" if rt == "dc" else "AGM → customer",
                   "Freight terms": tname,
                   "AGM → DC freight": "Sensata" if rt == "dc" else "no DC",
                   "Transport to customer": "Sensata" if t["freight"] else "Customer",
                   "Cargo insurance": "Sensata" if t["insurance"] else "–",
                   "Import duty": "Sensata (DC imports)" if rt == "dc" else ("Sensata" if t["duty"] else "Customer"),
                   "DC warehouse cost": "yes" if rt == "dc" else "no"})
    st.dataframe(pd.DataFrame(tr), hide_index=True)
    with st.expander("All Incoterms 2020"):
        st.dataframe(pd.DataFrame([{"Term": tn, "Mode": "Sea only" if t["sea"] else "Any mode",
                                    "Main transport": "Seller" if t["freight"] else "Buyer",
                                    "Cargo insurance": "Seller" if t["insurance"] else "–",
                                    "Import duty": "Seller" if t["duty"] else "Buyer",
                                    "What it means": t["desc"]} for tn, t in INCOTERMS.items()]),
                     hide_index=True, column_config={"What it means": st.column_config.TextColumn(width="large")})

    st.subheader("Landed cost per unit (Sensata's cost)")
    lrows = []
    for pk in PKEYS:
        for m, sh in (("US", P["products"][pk]["us_share"]), ("EU", 1 - P["products"][pk]["us_share"])):
            if sh <= 0:
                continue
            s, lch = unit_landed(P, pk, m, "steady"), unit_landed(P, pk, m, "launch")
            lrows.append({"Product": PNAME[pk], "Market": MARKETS[m], "Share of product": f"{sh * 100:.0f}%",
                          "Material incl. MOH": s["material"], "CLAM steady": s["clam"], "Freight": s["freight"],
                          "Insurance": s["insurance"], "Duty %": s["rate"] * 100, "Duty paid by": s["duty_payer"],
                          "Duty $": s["duty"], "Landed steady": s["landed"], "Landed launch": lch["landed"],
                          "ASP": s["asp"], "Unit margin steady": s["asp"] - s["landed"]})
    ldf = pd.DataFrame(lrows)
    st.dataframe(ldf.style.format({c: "{:.4f}" for c in ldf.columns if pd.api.types.is_numeric_dtype(ldf[c])}),
                 hide_index=True)
    st.caption("Pending cost + the freight, insurance and duty Sensata pays under the selected route and terms, at "
               "launch ASP. Warehouse and outbound freight (% of revenue) come on top for the DC route. The business "
               "case adds yield, inflation and productivity over time (Unit cost tab).")

    # US exposure over the horizon
    tot, shs = build_volumes(P)
    us_vol = {pk: tot * shs[pk] * P["products"][pk]["us_share"] for pk in PKEYS}
    us_total = sum(v.sum() for v in us_vol.values())
    all_total = tot.sum()
    mfn_us = P["duty"][("MX", "US")]["mfn"]

    st.subheader("USA: what the origin status costs")
    scen = [("USMCA-qualifying", {"pref": True}, False),
            ("Not USMCA: MFN + 10% (Section 301)", {"pref": False}, False),
            ("Not USMCA + Section 232 auto parts", {"pref": False}, True)]
    srows, scen_units = [], []
    for name, patch, s2 in scen:
        Pp = patched({("MX", "US"): patch, ("MX", "EU"): {"pref": True}}, s232=s2)  # EU set to 0 to isolate US duties
        hn = unit_landed(Pp, "HSSI_NA", "US")
        scen_units.append((name, hn))
        srows.append({"Scenario": name, "Rate %": duty_rate(Pp, ("MX", "US")) * 100,
                      "HSSI NA duty paid by Sensata $/unit (launch)": hn["duty"],
                      "US volume (k units)": us_total,
                      "US duties paid by Sensata over horizon ($k)": evaluate(Pp, COMBINED)["df"]["Finished-goods duties"].sum()})
    sdf = pd.DataFrame(srows)
    st.dataframe(sdf.style.format({"Rate %": "{:.1f}", "HSSI NA duty paid by Sensata $/unit (launch)": "{:.4f}",
                                   "US volume (k units)": "{:,.1f}", "US duties paid by Sensata over horizon ($k)": "{:,.0f}"}),
                 hide_index=True)
    if P["route"]["US"] == "direct" and not INCOTERMS[term_of(P, "US")]["duty"]:
        st.info(f"With {term_of(P, 'US').split(' –')[0]} on the direct route the customer pays the US import duty, so "
                "it is not in Sensata's cost. The customer will still price it in.")

    npv_usmca = npv_with({("MX", "US"): {"pref": True}})
    npv_no_usmca = npv_with({("MX", "US"): {"pref": False}}, s232=False)
    npv_232 = npv_with({("MX", "US"): {"pref": False}}, s232=True)
    npv_eu_pref = npv_with({("MX", "EU"): {"pref": True}})
    npv_eu_nopref = npv_with({("MX", "EU"): {"pref": False}})
    st.dataframe(pd.DataFrame({
        "Combined NPV ($k) if…": ["USMCA-qualifying", "Not USMCA (MFN + 10%)", "Not USMCA + Section 232",
                                  "EU origin proven (0%)", "EU origin not proven (MFN)"],
        "NPV": [npv_usmca, npv_no_usmca, npv_232, npv_eu_pref, npv_eu_nopref]}).style.format({"NPV": "{:,.0f}"}),
        hide_index=True)

    st.subheader("Sales route: via Sensata DC vs direct to customer")
    P_dc, P_dir = patched(route={"US": "dc", "EU": "dc"}), patched(route={"US": "direct", "EU": "direct"})
    st.caption("Freight terms used: via DC – " + ", ".join(f"{MARKETS[m]} {term_of(P_dc, m).split(' –')[0]}" for m in ["US", "EU"])
               + "; direct – " + ", ".join(f"{MARKETS[m]} {term_of(P_dir, m).split(' –')[0]}" for m in ["US", "EU"])
               + ". The route not selected in the sidebar uses the default terms (DAP via DC, DDP direct).")
    rrows = []
    for pk in PKEYS:
        for m, sh in (("US", P["products"][pk]["us_share"]), ("EU", 1 - P["products"][pk]["us_share"])):
            if sh <= 0:
                continue
            a, b_ = unit_landed(P_dc, pk, m), unit_landed(P_dir, pk, m)
            rrows.append({"Product": PNAME[pk], "Market": MARKETS[m], "Duty rate %": a["rate"] * 100,
                          "Customs value via DC": a["cv"], "Duty via DC": a["duty"],
                          "Customs value direct": b_["cv"], "Duty direct (Sensata)": b_["duty"],
                          "Freight + insurance via DC": a["freight"] + a["insurance"],
                          "Freight + insurance direct": b_["freight"] + b_["insurance"],
                          "Selected": ROUTE_NAME[P["route"][m]]})
    rdf_route = pd.DataFrame(rrows)
    st.dataframe(rdf_route.style.format({c: "{:.4f}" for c in rdf_route.columns
                                         if pd.api.types.is_numeric_dtype(rdf_route[c]) and c != "Duty rate %"}
                                        | {"Duty rate %": "{:.1f}"}), hide_index=True)
    combos = [("USA via DC, Europe via DC", {"US": "dc", "EU": "dc"}),
              ("USA via DC, Europe direct", {"US": "dc", "EU": "direct"}),
              ("USA direct, Europe via DC", {"US": "direct", "EU": "dc"}),
              ("USA direct, Europe direct", {"US": "direct", "EU": "direct"})]
    combo_rows = []
    for name, rt in combos:
        dfc = (r_ := evaluate(patched(route=rt), COMBINED))["df"]
        combo_rows.append({"Sales route": name, "Duties ($k)": dfc["Finished-goods duties"].sum(),
                           "Freight + insurance ($k)": dfc["Freight MS→DC"].sum() + dfc["Cargo insurance"].sum(),
                           "Warehouse + outbound ($k)": dfc["Warehouse"].sum() + dfc["Outbound freight"].sum(),
                           "Combined NPV ($k)": r_["npv"], "Selected": "✔" if rt == P["route"] else ""})
    combo_df = pd.DataFrame(combo_rows)
    st.dataframe(combo_df.style.format({c: "{:,.0f}" for c in combo_df.columns if c not in ("Sales route", "Selected")}),
                 hide_index=True)

    with details("Step-by-step calculations"):
        a_, b_ = unit_landed(P_dc, "HSSI_NA", "US"), unit_landed(P_dir, "HSSI_NA", "US")
        st.markdown(f"- Freight HSSI NA AGM → USA: {P['costs']['HSSI_NA']['weight_g']:.0f} g = "
                    f"{P['costs']['HSSI_NA']['weight_g'] / 1000:.3f} kg × {P['freight_kg'][('MX', 'US')]:.2f} $/kg = "
                    f"**{a_['lane_freight']:.4f}** $/unit")
        st.markdown(f"- Customs value HSSI NA via DC (USA, FOB – no freight): ({a_['material']:.5f} + {a_['clam']:.5f}) × "
                    f"(1 + {P['tp_markup']:.1f}%) = **{a_['cv']:.4f}**; duty {a_['rate'] * 100:.1f}% × {a_['cv']:.4f} = "
                    f"**{a_['duty']:.4f}** $/unit")
        t_dir = term_of(P_dir, "US")
        if INCOTERMS[t_dir]["duty"]:
            st.markdown(f"- Direct, {t_dir.split(' –')[0]}: customs value (ASP {b_['asp']:.4f} − freight {b_['freight']:.4f} − "
                        f"insurance {b_['insurance']:.4f}) ÷ (1 + {b_['rate'] * 100:.1f}%) = **{b_['cv']:.4f}**; duty "
                        f"{b_['rate'] * 100:.1f}% × {b_['cv']:.4f} = **{b_['duty']:.4f}** $/unit; difference vs DC "
                        f"**{b_['duty'] - a_['duty']:.4f}** $/unit")
        else:
            st.markdown(f"- Direct, {t_dir.split(' –')[0]}: the customer pays the import duty → Sensata's duty cost **0**")
        if P["products"]["HSSI_EU"]["us_share"] < 1:
            ae = unit_landed(P_dc, "HSSI_EU", "EU")
            st.markdown(f"- Customs value HSSI EU via DC (EU, CIF – with freight): ({ae['material']:.5f} + {ae['clam']:.5f}) × "
                        f"(1 + {P['tp_markup']:.1f}%) + {ae['lane_freight']:.4f} = **{ae['cv']:.4f}**")
        for name, hn in scen_units:
            st.markdown(f"- {name}: duty paid by Sensata {hn['duty']:.4f} $/unit; landed = {hn['material']:.5f} + "
                        f"{hn['clam']:.5f} + {hn['freight']:.4f} + {hn['insurance']:.4f} + {hn['duty']:.4f} = "
                        f"**{hn['landed']:.4f}**")
        st.markdown(f"- US volume = HSSI NA {us_vol['HSSI_NA'].sum():,.1f} + Gamma × {P['products']['GAMMA']['us_share'] * 100:.0f}% "
                    f"{us_vol['GAMMA'].sum():,.1f} = **{us_total:,.1f}** k units of {all_total:,.1f} "
                    f"({us_total / all_total * 100 if all_total else 0:.1f}%)")
        st.markdown(f"- Value of USMCA = {k(npv_usmca)} − ({k(npv_no_usmca)}) = **{k(npv_usmca - npv_no_usmca)}** $k NPV")

    st.subheader("Takeaways")
    takeaway("Tariffs", "warn", "USMCA origin is worth real money",
             f"Combined NPV {k(npv_usmca)} $k with USMCA vs {k(npv_no_usmca)} $k without: "
             f"{k(npv_usmca - npv_no_usmca)} $k. US duties paid by Sensata without USMCA: {k(srows[1]['US duties paid by Sensata over horizon ($k)'])} $k "
             f"over the horizon. Material is ~{mat_share:.0f}% of the unit cost, so the origin of the components decides the qualification.",
             "Ask Trade Compliance for a USMCA origin analysis (regional value content / tariff shift) on the BOMs of "
             "90518125519 and 90518125533, and whether HTS 9026.20 is on the Section 232 auto parts list.")
    lvl = "ok" if npv_232 > 0 else "risk"
    takeaway("Tariffs", lvl, "Worst case: Section 232 without USMCA",
             f"Combined NPV {k(npv_232)} $k if the US duty is MFN + 25% ({(mfn_us + 0.25) * 100:.1f}%).",
             "The case survives the worst tariff case; keep USMCA as upside." if lvl == "ok" else
             "The case does not survive the worst tariff case: USMCA qualification is a precondition for the go decision.")
    takeaway("Tariffs", "info", f"{us_total / all_total * 100 if all_total else 0:.0f}% of the volume goes to the USA",
             f"HSSI NA (100% USA) + {P['products']['GAMMA']['us_share'] * 100:.0f}% of Gamma = {us_total:,.1f} of "
             f"{all_total:,.1f} k units. Only this part is exposed to US duties.",
             "Confirm the Gamma USA / Europe split with Sales; it moves the tariff exposure directly.")
    best = max(combo_rows, key=lambda r: r["Combined NPV ($k)"])
    cur = [r for r in combo_rows if r["Selected"]][0]
    all_dc, all_dir = combo_rows[0], combo_rows[3]
    takeaway("Tariffs", "ok" if best is cur else "warn", f"Best sales route on current inputs: {best['Sales route']}",
             f"Via DC (both markets): duties {k(all_dc['Duties ($k)'])}, freight + insurance "
             f"{k(all_dc['Freight + insurance ($k)'])}, warehouse + outbound {k(all_dc['Warehouse + outbound ($k)'])} $k, "
             f"NPV {k(all_dc['Combined NPV ($k)'])} $k. Direct (both): duties {k(all_dir['Duties ($k)'])}, freight + "
             f"insurance {k(all_dir['Freight + insurance ($k)'])}, warehouse + outbound "
             f"{k(all_dir['Warehouse + outbound ($k)'])} $k, NPV {k(all_dir['Combined NPV ($k)'])} $k. The DC route uses a "
             f"{P['tp_markup']:.1f}% intercompany mark-up (placeholder).",
             ("The selected route is the best one." if best is cur else
              f"The selected route gives {k(best['Combined NPV ($k)'] - cur['Combined NPV ($k)'])} $k less NPV than the best one.")
             + " Confirm the intercompany price AGM → Fort Worth / Bergkirchen with Tax and the importer of record with "
               "Trade Compliance before choosing.")
    for m in ["US", "EU"]:
        tname, rt = term_of(P, m), P["route"][m]
        t = INCOTERMS[tname]
        if rt == "direct" and not t["duty"]:
            takeaway("Tariffs", "info", f"{MARKETS[m]}: with {tname.split(' –')[0]} the customer pays the import duty",
                     f"Direct route, {tname}: the duty is not in Sensata's cost"
                     + ("" if t["freight"] else ", and neither is the transport") + ".",
                     "Check that the quoted ASP is on the same terms; a customer paying duty and freight expects a lower price.")
        if rt == "dc" and not t["freight"]:
            takeaway("Tariffs", "info", f"{MARKETS[m]}: with {tname.split(' –')[0]} the customer collects at the DC",
                     "Outbound freight from the DC is the customer's cost, so it is not in the business case.",
                     "Check that the quoted ASP is on the same terms.")
    takeaway("Tariffs", "info", "Europe: the duty is a small factor",
             f"Combined NPV {k(npv_eu_pref)} $k with proven EU origin vs {k(npv_eu_nopref)} $k without "
             f"({k(npv_eu_pref - npv_eu_nopref)} $k).",
             "Prove Mexican origin under the EU–Mexico agreement (supplier declarations); check the MFN rate in TARIC.")


# ---------- 4. COMBINED VS SEPARATE ----------
with tabs[5]:
    show_guide("portfolio")
    st.header("One business case or three?")
    shares_all = lifetime_shares(P, PKEYS)
    comb = evaluate(P, COMBINED)
    sa_f = P["standalone_share"] / 100
    rows, standalone, allocated, incremental = [], {}, {}, {}
    for pk in PKEYS:
        standalone[pk] = run_set(P, {pk: sa_f})
        allocated[pk] = run_set(P, {pk: shares_all[pk]})
        others = [p for p in PKEYS if p != pk]
        incremental[pk] = comb["npv"] - run_set(P, lifetime_shares(P, others), full=False)["npv"]

    def row(view, prod, r):
        return {"View": view, "Product": prod, "NPV ($k)": r["npv"], "IRR": pct(r["irr"]),
                "Payback (yrs)": years_fmt(r["payback"]), "Net revenue ($k)": r["total_nr"],
                "Avg CM %": r["avg_cm_pct"]}

    rows.append(row("Combined", "All 3", comb))
    for pk in PKEYS:
        rows.append(row("Stand-alone", PNAME[pk], standalone[pk]))
    for pk in PKEYS:
        rows.append(row("Allocated", PNAME[pk], allocated[pk]))
    for pk in PKEYS:
        rows.append({"View": "Incremental", "Product": PNAME[pk], "NPV ($k)": incremental[pk]})
    sum_sa = sum(standalone[pk]["npv"] for pk in PKEYS)
    synergy = comb["npv"] - sum_sa
    rows.append({"View": "Synergy", "Product": "Combined − Σ stand-alone", "NPV ($k)": synergy})
    rdf = pd.DataFrame(rows)

    c = st.columns(3)
    c[0].metric("Combined NPV ($k)", k(comb["npv"]))
    c[1].metric("Σ stand-alone NPV ($k)", k(sum_sa))
    c[2].metric("Synergy ($k)", k(synergy))

    fig = go.Figure()
    names = [PNAME[pk] for pk in PKEYS]
    fig.add_bar(x=names, y=[standalone[pk]["npv"] for pk in PKEYS], name="Stand-alone")
    fig.add_bar(x=names, y=[allocated[pk]["npv"] for pk in PKEYS], name="Allocated")
    fig.add_bar(x=names, y=[incremental[pk] for pk in PKEYS], name="Incremental")
    fig.add_hline(y=0, line_dash="dash", line_color="gray")
    fig.update_layout(barmode="group", title="NPV per product by view ($k)", height=320)
    st.plotly_chart(fig)

    st.markdown("**Full comparison table**")
    st.dataframe(rdf.style.format({"NPV ($k)": "{:,.0f}", "Net revenue ($k)": "{:,.0f}", "Avg CM %": "{:.1f}%"},
                                  na_rep="–"), hide_index=True)

    with details("Step-by-step calculations"):
        st.markdown("Volume share over the horizon (allocation key for shared costs): " + ", ".join(
            f"{PNAME[pk]} {shares_all[pk] * 100:.1f}%" for pk in PKEYS))
        shared_capex = P["capex_y1"] + P["capex_y2"] + P["capex_launch"]
        st.markdown(f"- Shared CapEx {k(shared_capex)} $k: allocated " + ", ".join(
            f"{PNAME[pk]} {shared_capex:,.0f} × {shares_all[pk] * 100:.1f}% = {shared_capex * shares_all[pk]:,.1f}"
            for pk in PKEYS) + f"; stand-alone each carries {shared_capex:,.0f} × {P['standalone_share']}% = "
                               f"{shared_capex * sa_f:,.1f}")
        st.markdown(f"- Allocated sum: {' + '.join(k(allocated[pk]['npv']) for pk in PKEYS)} = "
                    f"{k(sum(allocated[pk]['npv'] for pk in PKEYS))} $k vs combined {k(comb['npv'])} $k "
                    "(equal when tax = 0%)")
        for pk in PKEYS:
            st.markdown(f"- Incremental {PNAME[pk]} = combined {k(comb['npv'])} − combined without it "
                        f"{k(comb['npv'] - incremental[pk])} = **{k(incremental[pk])}** $k")
        st.markdown(f"- Synergy = {k(comb['npv'])} − ({' + '.join(k(standalone[pk]['npv']) for pk in PKEYS)}) = "
                    f"**{k(synergy)}** $k")

    st.subheader("Takeaways")
    takeaway("Combined vs separate", "ok" if synergy > 0 else "info",
             "Present the project as one business case",
             f"Synergy {k(synergy)} $k: the shared CapEx, RD&E and SG&A are paid once for three products. "
             f"Separately, each product would carry {P['standalone_share']}% of them on its own.",
             "Decide on the combined case, and show the incremental NPV of each product next to it.")
    for pk in PKEYS:
        inc, sa = incremental[pk], standalone[pk]["npv"]
        if inc < 0:
            takeaway("Combined vs separate", "risk", f"{PNAME[pk]} reduces the value of the project",
                     f"Incremental NPV {k(inc)} $k: the combined case is better without this product. "
                     "The other products are subsidising it.",
                     "Reprice, reduce cost (Gamma ramp-up, material) or take the product out of scope.")
        elif sa < 0:
            takeaway("Combined vs separate", "warn", f"{PNAME[pk]} only works inside the package",
                     f"Stand-alone NPV {k(sa)} $k (cannot carry the shared costs alone), incremental NPV {k(inc)} $k.",
                     "Do not evaluate it as a separate case; keep it in the combined case and watch its volume.")
        else:
            takeaway("Combined vs separate", "ok", f"{PNAME[pk]} also stands on its own",
                     f"Stand-alone NPV {k(sa)} $k, incremental NPV {k(inc)} $k.",
                     "No cross-subsidy needed.")


# ---------- 9. SCENARIOS & SENSITIVITY ----------
with tabs[6]:
    show_guide("scenarios")
    st.header(f"Scenarios – {view_tag}")
    presets = {
        "Base": dict(vol=0, asp=0, mat=0, clam=0, capex=0),
        "Upside": dict(vol=15, asp=5, mat=-5, clam=-5, capex=0),
        "Downside": dict(vol=-15, asp=-5, mat=10, clam=10, capex=10),
    }
    preset = st.selectbox("Start from preset", list(presets.keys()), index=2)
    pv = presets[preset]
    s = st.columns(5)
    sv = s[0].slider("Volume %", -50, 50, pv["vol"], key=f"{preset}_vol")
    sa = s[1].slider("ASP %", -30, 30, pv["asp"], key=f"{preset}_asp")
    sm = s[2].slider("Material cost %", -30, 30, pv["mat"], key=f"{preset}_mat")
    sc = s[3].slider("CLAM %", -30, 30, pv["clam"], key=f"{preset}_clam")
    sk = s[4].slider("CapEx %", -50, 100, pv["capex"], key=f"{preset}_capex")

    scen_r = evaluate(P, VIEW, vol_mult=1 + sv / 100, asp_mult=1 + sa / 100, mat_mult=1 + sm / 100,
                      clam_mult=1 + sc / 100, capex_mult=1 + sk / 100)

    compare = pd.DataFrame({
        "Metric": ["Total net revenue ($k)", "Avg contribution margin", "NPV ($k)", "IRR", "Payback (years)", "ROI"],
        "Base": [f"{base['total_nr']:,.0f}", f"{base['avg_cm_pct']:.1f}%", f"{base['npv']:,.0f}",
                 pct(base["irr"]), years_fmt(base["payback"]), pct(base["roi"])],
        "Scenario": [f"{scen_r['total_nr']:,.0f}", f"{scen_r['avg_cm_pct']:.1f}%", f"{scen_r['npv']:,.0f}",
                     pct(scen_r["irr"]), years_fmt(scen_r["payback"]), pct(scen_r["roi"])],
    })
    st.dataframe(compare, hide_index=True)

    fig = go.Figure()
    fig.add_scatter(x=years, y=base["df"]["Cumulative FCF"], name="Base cumulative FCF", mode="lines+markers")
    fig.add_scatter(x=years, y=scen_r["df"]["Cumulative FCF"], name="Scenario cumulative FCF", mode="lines+markers")
    fig.add_hline(y=0, line_dash="dash", line_color="gray")
    fig.update_layout(title="Cumulative FCF: base vs scenario ($k)")
    st.plotly_chart(fig)

    st.divider()
    st.header("Sensitivity (tornado)")
    shock = st.slider("Shock size ± %", 5, 30, 10)
    levers = {
        "Volume": lambda m: dict(vol_mult=m),
        "ASP": lambda m: dict(asp_mult=m),
        "Material cost": lambda m: dict(mat_mult=m),
        "CLAM": lambda m: dict(clam_mult=m),
        "CapEx": lambda m: dict(capex_mult=m),
    }
    rows = []
    for name, fn in levers.items():
        lo = evaluate(P, VIEW, full=False, **fn(1 - shock / 100))["npv"] - base["npv"]
        hi = evaluate(P, VIEW, full=False, **fn(1 + shock / 100))["npv"] - base["npv"]
        rows.append((name, f"-{shock}%", lo, f"+{shock}%", hi))
    lo = evaluate(P, VIEW, full=False, rate_delta=-0.02)["npv"] - base["npv"]
    hi = evaluate(P, VIEW, full=False, rate_delta=+0.02)["npv"] - base["npv"]
    rows.append(("WACC", "-2 pp", lo, "+2 pp", hi))
    rows.sort(key=lambda r: max(abs(r[2]), abs(r[4])))

    fig = go.Figure()
    fig.add_bar(y=[r[0] for r in rows], x=[r[2] for r in rows], orientation="h", name="Lever down",
                text=[r[1] for r in rows])
    fig.add_bar(y=[r[0] for r in rows], x=[r[4] for r in rows], orientation="h", name="Lever up",
                text=[r[3] for r in rows])
    fig.update_layout(barmode="overlay", title=f"Change in NPV vs base ({base['npv']:,.0f} $k)",
                      xaxis_title="Δ NPV ($k)")
    st.plotly_chart(fig)

    st.subheader("Takeaways")
    top, second = rows[-1], rows[-2]
    takeaway("Scenarios", "info", f"{top[0]} is the biggest lever, then {second[0]}",
             f"±{shock}% {top[0]} moves the NPV by {k(top[2])} / {k(top[4])} $k; "
             f"{second[0]} by {k(second[2])} / {k(second[4])} $k.",
             f"Spend the data-quality effort on {top[0]} and {second[0]} first.")
    lvl = "ok" if scen_r["npv"] > 0 else "risk"
    takeaway("Scenarios", lvl, f"{preset} scenario: NPV {k(scen_r['npv'])} $k",
             f"Volume {sv:+d}%, ASP {sa:+d}%, material {sm:+d}%, CLAM {sc:+d}%, CapEx {sk:+d}%.",
             "The case holds in this scenario." if lvl == "ok" else
             "The case does not hold in this scenario: agree mitigation (price, volume commitment) before go.")


# ---------- 10. MONTE CARLO ----------
with tabs[6]:
    show_guide("montecarlo")
    st.divider()
    st.header(f"Monte Carlo simulation – {view_tag}")
    st.caption("Runs only when you press the button, so moving other sliders stays fast.")

    m = st.columns(3)
    sims = m[0].slider("Number of simulations", 200, 5000, 1000, step=100)
    seed = m[1].number_input("Random seed", 0, 99999, 42, help="Same seed + same inputs = same result.")
    vol_std = m[2].slider("Volume level volatility (± %)", 0.0, 40.0, 15.0)
    m = st.columns(3)
    asp_std = m[0].slider("Price-down volatility (± pp per year)", 0.0, 5.0, 1.0,
                          help="Shifts every year's price-down by the same random amount (can be negative).")
    mat_std = m[1].slider("Material productivity volatility (± pp)", 0.0, 5.0, 1.5)

    signature = (repr(sorted(P.items(), key=lambda x: x[0])), VIEW, sims, seed, vol_std, asp_std, mat_std)

    if st.button("Run simulation", type="primary"):
        rng = np.random.default_rng(int(seed))
        results = np.empty(sims)
        with st.spinner("Running simulations..."):
            for kk in range(sims):
                results[kk] = evaluate(
                    P, VIEW, full=False,
                    vol_mult=max(0.0, rng.normal(1.0, vol_std / 100)),
                    asp_shift=rng.normal(0.0, asp_std),
                    mat_prod=max(0.0, rng.normal(P["mat_prod"], mat_std)),
                )["npv"]
        st.session_state["mc"] = {"sig": signature, "npv": results}

    mc = st.session_state.get("mc")
    if mc is None:
        st.info("Press 'Run simulation' to see the NPV distribution.")
    else:
        if mc["sig"] != signature:
            st.warning("Inputs changed since the last run. Press 'Run simulation' to refresh.")
        r = mc["npv"]
        fig = px.histogram(r, nbins=50, title="NPV distribution ($k)")
        fig.add_vline(x=0, line_dash="dash", line_color="red")
        fig.update_layout(showlegend=False)
        st.plotly_chart(fig)
        c = st.columns(4)
        c[0].metric("Mean NPV ($k)", f"{r.mean():,.0f}")
        c[1].metric("P5 NPV ($k)", f"{np.percentile(r, 5):,.0f}", help="5% of outcomes are worse than this.")
        c[2].metric("P95 NPV ($k)", f"{np.percentile(r, 95):,.0f}", help="5% of outcomes are better than this.")
        c[3].metric("P(NPV > 0)", f"{(r > 0).mean() * 100:.1f}%")

        st.subheader("Takeaways")
        prob = (r > 0).mean() * 100
        lvl = "ok" if prob >= 90 else ("warn" if prob >= 60 else "risk")
        takeaway("Monte Carlo", lvl, f"The project is profitable in {prob:.0f} of 100 simulated futures",
                 f"Mean NPV {k(r.mean())} $k, bad case P5 {k(np.percentile(r, 5))} $k, good case P95 "
                 f"{k(np.percentile(r, 95))} $k ({sims} runs, volume ±{vol_std:.0f}%).",
                 "Robust to forecast error." if lvl == "ok" else
                 "The downside is material: secure volume commitments or price floors before go.")




# ---------- 8. EXPLAIN ----------
with tabs[7]:
    show_guide("explain")
    st.subheader("Data register – where every input comes from")
    OK, AS, PH = "✅ confirmed", "🟡 assumption", "🔴 placeholder"
    vt = [v for v in P["vol_table"] if v]
    split0 = P["share_table"][0] if P["share_table"] else {pk: 1 / 3 for pk in PKEYS}
    pdn = ", ".join(f"{d * 100:.1f}%" for d in P["price_down"] if d) or "none"
    lanes_txt = "; ".join(f"MX→{m}: {duty_rate(P, ('MX', m)) * 100:.1f}%" for m in ("US", "EU"))
    reg = [
        ("Volume", "Volume forecast (3 products)", f"{vt[0]:,.1f} … {vt[-1]:,.1f} k units" if vt else "–",
         "Project forecast (original model)", "Sales", AS,
         "Customer forecast / Demantra is the standard source in the Excel Data Register; confirm it is the latest."),
        ("Volume", "Split between the products", " / ".join(f"{split0[pk] * 100:.1f}%" for pk in PKEYS),
         "Not yet received", "Sales", PH, "Equal split until the real split is known; it moves the US duty exposure."),
        ("Volume", "Gamma sold in the USA", f"{P['products']['GAMMA']['us_share'] * 100:.0f}%", "Not yet received",
         "Sales", PH, "HSSI NA is 100% USA and HSSI EU 100% Europe by definition; Gamma goes to both."),
        ("Price", "Selling price A / B", f"{P['price_A']:.2f} / {P['price_B']:.2f} $/unit", "Commercial proposal",
         "Sales", OK, "The two probable prices given for the quote; both are always compared on the Decision tab."),
        ("Price", "Price-down", f"{pdn} ({'year-on-year' if P['price_down_mode'] == 'yoy' else 'discount on quote'})",
         "Commercial proposal", "Sales", AS,
         "1% in the first two years; confirm whether the price stays down (year-on-year) or returns to the quote."),
        ("Unit cost", "MAT, MOH, RES, OH per product",
         "HSSI 4.885 + Gamma 5.852 $/unit material quote applied" if any(pk in MATERIAL_QUOTE for pk in PKEYS)
         and not [e for e in P["cost_edited"] if "MOH" in e or "RES" in e or "OH" in e]
         else ("edited – see Unit cost tab" if P["cost_edited"] else "as reported, no edits"),
         "Item Readiness Report, pending cost, AGM + material quote received directly",
         "Procurement / Finance make site", OK,
         "MOH, RES and OH are the Item Readiness Report pending cost; MAT uses the material quote received directly "
         "(4.885 $/unit HSSI, 5.852 $/unit Gamma), overriding the report's MAT."),
        ("Unit cost", "Gamma ramp-up in AGM",
         f"{P['gamma_clam_launch']:.3f} → {P['gamma_clam_steady']:.3f} $/unit in {P['gamma_years']} yrs" if P["gamma_ramp"] else "off",
         "Model assumption", "Finance make site (AGM)", AS,
         "Gamma's conversion is ~10× HSSI's in the same plant; target = the HSSI level (mature process)."),
        ("Unit cost", "Yield launch → steady", f"{P['yield_launch']:.1f}% → {P['yield_steady']:.1f}%",
         "Company Excel template", "Finance make site", AS, "Standard cost already holds the planned scrap; only the extra launch scrap is added."),
        ("Unit cost", "Material productivity", f"{P['mat_prod']:.1f}% / year", "Company Excel template",
         "Procurement", AS, "The Excel lets the material cost fall about 2% a year."),
        ("Unit cost", "Labour inflation / launch CLAM premium",
         f"{P['labour_infl']:.1f}% / {P['clam_premium']:.1f}× for {P['conv_years']} yrs", "Original model",
         "Finance make site", AS, "Learning curve at launch; labour cost inflation over the years."),
        ("Logistics", "Freight AGM → DC", f"USA {P['freight_kg'][('MX', 'US')]:.2f} / Europe {P['freight_kg'][('MX', 'EU')]:.2f} $/kg",
         "Not yet received", "Logistics", PH, "Ask Logistics for the trade-lane rates AGM → Fort Worth and AGM → Bergkirchen."),
        ("Logistics", "Duty rates (finished goods)", lanes_txt, "Tariff status September 2026", "Trade Compliance", AS,
         "No USMCA preference assumed (conservative); USMCA would make the US duty 0%."),
        ("Logistics", "Sales route & freight terms",
         "; ".join(f"{MARKETS[m]}: {ROUTE_NAME[P['route'][m]]}, {term_of(P, m).split(' –')[0]}" for m in ("US", "EU")),
         "Project set-up (DCs Fort Worth / Bergkirchen)", "Logistics / Trade Compliance", AS,
         "Via the DC the duty is on the intercompany price; direct to the customer it is on the selling price."),
        ("Logistics", "Intercompany mark-up", f"{P['tp_markup']:.1f}%", "Not yet received", "Tax", PH,
         "Sets the customs value on the DC route; the real transfer price comes from Tax."),
        ("Overhead COGS", "Outbound freight / warehouse / COPQ",
         f"{P['outbound_pct']:.1f}% / {P['warehouse_pct']:.1f}% / {P['copq_pct']:.2f}% of item revenue",
         "Company Excel (Cashflow model)", "Logistics / Finance", OK, "COPQ 1.28% = standard BU warranty accrual."),
        ("Investment", "Additional CapEx", f"{P['capex_y1'] + P['capex_y2'] + P['capex_launch']:,.0f} $k, "
         f"{P['dep_life']} yrs straight-line", "Company Excel template (Additional Investment)", "Operations / Finance", AS,
         "Confirm the equipment list and quotes for EZ Sensor Pro."),
        ("Investment", "RD&E labour / expenses / NRE",
         f"{P['rde_table']['Labour'].sum():,.0f} / {P['rde_table']['Expenses'].sum():,.0f} / {P['rde_table']['NRE'].sum():,.0f} $k",
         "Original model", "R&D / PMT", AS, "Replace with the RD&E labour and non-labour forecast of the project."),
        ("Investment", "SG&A", f"{P['sga_fixed']:,.0f} $k / year", "Company Excel", "Finance", OK,
         "One per region / product group, as noted in the Excel."),
        ("Cash", "Payment terms", f"{P['pay_days']} days = {P['pay_pct']:.1f}% of item revenue", "Company Excel (Payments terms)",
         "Finance / Treasury", OK, "Cost of giving the customer time to pay."),
        ("Cash", "DSO / DIO / DPO", f"{P['dso']} / {P['dio']} / {P['dpo']} days", "Company Excel", "Finance", OK,
         "Cash tied up in receivables and stock, minus what we owe suppliers."),
        ("Decision", "WACC", f"{P['wacc'] * 100:.1f}%", "Company Excel", "Finance", OK, "Minimum yearly return the company requires."),
        ("Decision", "Hurdles", ", ".join(f"{h:.1f}%" for _, h in P["mm_hurdles"]) + f"; payback < {P['payback_hurdle']} yrs",
         "Company Excel (Investment Decision)", "Finance", OK, "Margin benchmarks: TMS, TPMS and Sensata worldwide."),
        ("Decision", "Income tax", f"{P['tax_rate']:.0f}%", "Company Excel ('Income tax?')", "Finance", OK,
         "Pre-tax analysis, as in the Excel."),
    ]
    reg_df = pd.DataFrame(reg, columns=["Area", "Input", "Value in the model", "Source", "Owner", "Status", "Why"])
    n_ph = (reg_df["Status"] == PH).sum()
    n_as = (reg_df["Status"] == AS).sum()
    c = st.columns(3)
    c[0].metric("Confirmed inputs", int((reg_df["Status"] == OK).sum()))
    c[1].metric("Assumptions to confirm", int(n_as))
    c[2].metric("Placeholders to replace", int(n_ph))
    st.dataframe(reg_df, hide_index=True, column_config={"Why": st.column_config.TextColumn(width="large")})

    st.subheader("Company Cash Flow Excel vs this model")
    align = [
        ("Volume × ASP = item revenue", "Same", "Volume per year × price per year; the price comes from price A / B and the price-down table."),
        ("Quicksavings amortization", "Same", "Spread over the years in proportion to volume."),
        ("Material cost = unyielded ÷ yield + freight + tariffs", "Same logic",
         "MAT ÷ yield + MOH (MOH = inbound freight and duties from the Item Readiness Report)."),
        ("CLAM = labour time × rate + indirect + spares + depreciation", "Same result, other input",
         "The Item Readiness Report gives labour (RES) and overhead (OH) directly in $/unit."),
        ("Additional investment depreciation = CapEx ÷ 10 ÷ volume", "Same", "Straight-line over the useful life, from the launch year."),
        ("Freight and duties (MS→DC)", "More detail", "Per lane (AGM → Fort Worth / Bergkirchen), with duty rates, sales route and freight terms."),
        ("Outbound 1%, warehouse 0.4%, COPQ 1.28% of revenue", "Same", "Warehouse and outbound only where a DC is used."),
        ("RD&E labour, expenses, NRE by year", "Same", "Year table in the sidebar; NRE lowers the RD&E cost."),
        ("SG&A fixed per year", "Same", "100 $k a year from launch."),
        ("Cost of payment terms from the days table", "Same", "60 days = 1% of item revenue."),
        ("Contribution margin", "Same", "Gross margin − RD&E − SG&A − payment terms."),
        ("FCF = CM + payment terms + depreciation + CapEx + Δ working capital", "Same logic",
         "CapEx is taken off as a cash outflow; working capital = receivables + inventory − payables."),
        ("NPV with Excel NPV() at 12%", "Same", "First year discounted by one full year."),
        ("Payback in full years from the project start", "Same", "Interpolated inside the year it turns positive."),
        ("Money in $", "Different unit", "This model shows $k (thousands); volumes in k units."),
    ]
    st.dataframe(pd.DataFrame(align, columns=["Company Excel", "This model", "How"]), hide_index=True,
                 column_config={"How": st.column_config.TextColumn(width="large")})

    st.subheader("All takeaways")
    tk = pd.DataFrame(TAKEAWAYS)
    if not tk.empty:
        order = {"❌ risk": 0, "⚠️ warn": 1, "✅ ok": 2, "ℹ️ info": 3}
        tk = tk.assign(_o=tk["Level"].map(order)).sort_values("_o", kind="stable").drop(columns="_o")
        st.dataframe(tk, hide_index=True, column_config={"Argument": st.column_config.TextColumn(width="large"),
                                                         "Action": st.column_config.TextColumn(width="large")})
        st.download_button("Download takeaways (CSV)", tk.to_csv(index=False).encode("utf-8-sig"), "takeaways.csv",
                           "text/csv")

    st.subheader("Glossary")
    for key_, title_ in [("overview", "How the model works"), ("decision", "Decision"), ("pl_excel", "P&L"),
                         ("cf_excel", "Cash flow"), ("unitcost", "Unit cost"), ("products", "Cost elements"),
                         ("tariffs", "Tariffs, routes and freight terms"), ("portfolio", "One case or three"),
                         ("scenarios", "Scenarios"), ("montecarlo", "Monte Carlo")]:
        with st.expander(title_):
            st.markdown(GUIDE[key_])


# ---------- 11. CUSTOM P&L INPUT ----------
with tabs[7]:
    show_guide("custom")
    st.divider()
    st.header("Stand-alone calculator: custom P&L input")
    st.write("Enter your own year-by-year figures ($k) to evaluate any business case directly.")

    c = st.columns(3)
    cs_year = c[0].number_input("Start year", 2000, 2100, 2026, key="custom_start_year")
    cs_n = c[1].number_input("Number of years", 2, 20, 10, step=1, key="custom_num_years")
    cs_rate = c[2].slider("Discount rate %", 0.0, 30.0, 12.0, key="custom_discount_rate")

    cyears = [str(y) for y in range(int(cs_year), int(cs_year) + int(cs_n))]
    template = pd.DataFrame({
        "Year": cyears,
        "Net revenue": [0.0] * len(cyears),
        "COGS": [0.0] * len(cyears),
        "Operating expenses": [0.0] * len(cyears),
        "Depreciation (included above)": [0.0] * len(cyears),
        "CapEx": [0.0] * len(cyears),
        "Change in working capital": [0.0] * len(cyears),
    })
    st.caption("Operating expenses = everything below gross margin (RD&E, SG&A, payment terms…). "
               "Depreciation: the part of COGS/OpEx that is depreciation; it is added back as non-cash. "
               "Change in working capital: positive = cash outflow.")
    ed = st.data_editor(template, num_rows="fixed", key="custom_pl_editor", disabled=["Year"], hide_index=True)

    ed["Gross margin"] = ed["Net revenue"] - ed["COGS"]
    ed["Gross margin %"] = np.where(ed["Net revenue"] != 0, ed["Gross margin"] / ed["Net revenue"].replace(0, np.nan) * 100, np.nan)
    ed["Contribution margin"] = ed["Gross margin"] - ed["Operating expenses"]
    ed["Free cash flow"] = (ed["Contribution margin"] + ed["Depreciation (included above)"]
                            - ed["CapEx"] - ed["Change in working capital"])
    ed["Cumulative FCF"] = ed["Free cash flow"].cumsum()

    cfcf = ed["Free cash flow"].tolist()
    c_npv = compute_npv(cs_rate / 100, cfcf, P["excel_npv"])
    c_irr = compute_irr(cfcf)
    c_pb = compute_payback(np.array(cfcf))

    c = st.columns(4)
    c[0].metric("Total net revenue ($k)", f"{ed['Net revenue'].sum():,.0f}")
    c[1].metric("NPV ($k)", f"{c_npv:,.0f}")
    c[2].metric("IRR", pct(c_irr))
    c[3].metric("Payback (years)", years_fmt(c_pb))

    if c_npv > 0:
        st.success(f"NPV is positive ({c_npv:,.0f} $k) at {cs_rate:.1f}%: the case creates value under these assumptions.")
    else:
        st.error(f"NPV is negative ({c_npv:,.0f} $k) at {cs_rate:.1f}%: the case does not earn the required return.")

    st.dataframe(statement(ed, ["Net revenue", "Gross margin", "Gross margin %", "Contribution margin",
                                "Free cash flow", "Cumulative FCF"], pct_rows=["Gross margin %"]))