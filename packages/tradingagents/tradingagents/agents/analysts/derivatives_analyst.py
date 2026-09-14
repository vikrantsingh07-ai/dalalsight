"""Derivatives (F&O) analyst for Indian instruments.

Reads exchange end-of-day F&O data (futures basis and open-interest build-up, the
option chain, participant-wise FII/DII/Pro/Client positioning and India VIX) and
turns it into a positioning report for the researchers and trader. Offered only
for NSE/BSE instruments that have exchange-traded derivatives.
"""

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.utils.agent_utils import (
    get_fii_derivatives_positioning,
    get_fno_futures_analysis,
    get_india_vix,
    get_instrument_context_from_state,
    get_language_instruction,
    get_option_chain_analysis,
)


def create_derivatives_analyst(llm):

    def derivatives_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = get_instrument_context_from_state(state)

        tools = [
            get_fno_futures_analysis,
            get_option_chain_analysis,
            get_fii_derivatives_positioning,
            get_india_vix,
        ]

        system_message = (
            """You are an Indian derivatives (F&O) market-structure analyst. Using NSE/BSE end-of-day exchange data, explain what futures and options positioning implies for the instrument. Call each tool: get_fno_futures_analysis(symbol, curr_date) for the futures price, basis and cost of carry, open-interest build-up and rollover; get_option_chain_analysis(symbol, curr_date) for put-call ratios, max pain, open-interest walls, the straddle-implied move and implied volatility (plus premium, IV and Greeks for a specific option contract); get_fii_derivatives_positioning(curr_date) for FII, DII, Pro and Client positioning; and get_india_vix(curr_date) for the volatility regime.

How to read the data:
- Open-interest build-up: price up with OI up is long build-up; price down with OI up is short build-up; price up with OI down is short covering; price down with OI down is long unwinding. Fresh positions (rising OI) carry more conviction than covering or unwinding.
- Basis: the futures premium over spot reflects cost of carry. An unusually thin or negative basis points to bearish positioning (or an upcoming dividend in a stock); an unusually rich premium points to aggressive longs.
- Rollover: in the final week before expiry, a high share of open interest already in later expiries shows traders carrying positions forward.
- Option chain: strikes with the highest call OI often act as resistance and those with the highest put OI as support; fresh OI additions show where option writers are defending. A PCR (OI) above 1 means more puts than calls are open, usually read as put writers supporting the market, though extreme readings can be contrarian. Max pain is where option buyers lose the most at expiry; price often drifts toward it near expiry, but it is not a price target.
- The ATM straddle premium gives the market-implied move to expiry; compare implied volatility with India VIX and recent realised moves.
- The FII index-futures long % is a widely watched gauge of institutional positioning; its direction over several sessions matters more than a single day, and retail clients often sit on the other side.
- India VIX: a rising VIX with falling prices signals fear and hedging demand; a very low VIX signals complacency and cheap options.

Rules: state the as-of session date of the data. Quote exact numbers only from tool output. If a tool says the instrument is not in the F&O segment or that data is unavailable, say so plainly and do not invent positioning. For a futures contract, cover basis, days to expiry, lot size, margin and mark-to-market risk, and roll timing. For an option contract, cover premium, implied volatility, Greeks, breakeven, time decay and lot-size risk. Conclude with the directional bias the derivatives data supports (bullish, bearish, range-bound or unclear), the key support and resistance levels from open interest, the expected move to expiry, and what would invalidate the view."""
            + """ Make sure to append a Markdown table at the end of the report to organize key points in the report, organized and easy to read."""
            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " Use the provided tools to progress towards answering the question."
                    " If you are unable to fully answer, that's OK; another assistant with different tools"
                    " will help where you left off. Execute what you can to make progress."
                    " If you or any other assistant has the FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** or deliverable,"
                    " prefix your response with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** so the team knows to stop."
                    " You have access to the following tools: {tool_names}."
                    " Today's date is {current_date}; treat it as 'now' for all analysis and tool-call date ranges. {instrument_context}\n"
                    "{system_message}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        chain = prompt | llm.bind_tools(tools)

        result = chain.invoke(state["messages"])

        report = ""

        if len(result.tool_calls) == 0:
            report = result.content

        return {
            "messages": [result],
            "derivatives_report": report,
        }

    return derivatives_analyst_node
