from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.utils.agent_utils import (
    get_balance_sheet,
    get_cashflow,
    get_corporate_events,
    get_fundamentals,
    get_income_statement,
    get_instrument_context_from_state,
    get_language_instruction,
)
from tradingagents.dataflows.india.instruments import EQUITY, parse_indian_symbol


def create_fundamentals_analyst(llm):
    def fundamentals_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = get_instrument_context_from_state(state)

        tools = [
            get_fundamentals,
            get_balance_sheet,
            get_cashflow,
            get_income_statement,
        ]

        role = "You are a researcher tasked with analyzing fundamental information over the past week about a company. Please write a comprehensive report of the company's fundamental information such as financial documents, company profile, basic company financials, and company financial history to gain a full view of the company's fundamental information to inform traders. Make sure to include as much detail as possible. Provide specific, actionable insights with supporting evidence to help traders make informed decisions."
        tool_guide = " Use the available tools: `get_fundamentals` for comprehensive company analysis, `get_balance_sheet`, `get_cashflow`, and `get_income_statement` for specific financial statements."

        # Indian instruments: an index is valued, not audited; NSE companies add
        # corporate events. Other markets keep the prompt above unchanged.
        indian = parse_indian_symbol(str(state.get("company_of_interest", "")))
        if indian is not None and indian.underlying_kind == "index":
            tools = [get_fundamentals]
            role = "You are a researcher analysing the fundamentals of an Indian stock-market index, which is not a company. Call `get_fundamentals` for the index's valuation history (P/E, P/B and dividend yield) and assess whether the index is cheap or expensive against its own history, what that implies for forward returns, and which earnings and macro drivers matter. Do not look for balance sheets or company financial statements. Provide specific, actionable insights with supporting evidence to help traders make informed decisions."
            tool_guide = ""
        elif indian is not None and indian.underlying_kind == "stock" and indian.exchange == "NSE":
            tools.append(get_corporate_events)
            subject = (
                "This is an NSE-listed company" if indian.segment == EQUITY
                else f"This derivatives contract is on the NSE-listed company {indian.underlying}; analyse that company"
            )
            tool_guide += f" {subject}: also call `get_corporate_events` for dividends, splits and bonus issues, results dates, board meetings and recent exchange filings. Figures are in INR (₹); Indian filings often use lakh (1e5) and crore (1e7)."

        system_message = (
            role
            + " Make sure to append a Markdown table at the end of the report to organize key points in the report, organized and easy to read."
            + tool_guide
            + get_language_instruction(),
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
            "fundamentals_report": report,
        }

    return fundamentals_analyst_node
