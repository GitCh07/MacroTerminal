# Macro Terminal: my notes

## The one-liner
- Runs on my laptop and reads US economic data straight from the Fed's database (FRED).
- Answers two questions: what is the economy doing right now, and what does that usually mean for markets?
- Turns about 20 indicators into a simple bullish / neutral / bearish lean for six markets, and shows its working.

## Where the idea came from
- Started from a "Macro Terminal" post on Instagram. It showed a market's bias, then the growth, jobs and inflation scores behind it, then history next to today.
- Borrowed exhibit ideas from a "Macro Monitor" PDF: recession odds, curve slope, credit spreads, financial conditions, term premium, sector moves.
- My build keeps the same idea, but every number is pulled live and every rule is written down.

## Where the data comes from
- **FRED (St. Louis Fed):** nearly everything. Free, official, the same source economists use. Needs a free API key.
- **Yahoo Finance:** S&P 500 history back to 1950 and the sector funds. FRED only holds 10 years of the S&P under its licence.
- **Federal Reserve website:** the latest policy statements and speeches.
- Two ways to run it: a hosted page that GitHub rebuilds on its own servers, or locally on my laptop. Both refresh on weekdays just after the big releases land (8:37 AM, 10:07 AM, 5:07 PM New York time). Refresh pulls on demand.

## What's on screen

### Board (the main page)
- **Regime:** where the economy sits on a growth-vs-inflation map. Four boxes:
  - Goldilocks: growth up, inflation down
  - Reflation: both up
  - Stagflation: growth down, inflation up
  - Slowdown: both down
- **Cycle checks:** four recession gauges. Covered under "How the recession checks work" below.
- **Market bias:** S&P 500, Nasdaq, Russell 2000, 10-year Treasuries, US dollar, gold. Each reads very bullish, bullish, neutral, bearish or very bearish.
- **What's driving it:** click a market to see every indicator pushing it up or down.
- **How this phase has tended to play out:** one-liners on what history says about this kind of regime, next to last month's sector returns.
- **Year after a midterm:** how the S&P did in the 12 months after every midterm since 1950, against how 2026 is tracking.
- **Since last visit:** what changed since I last checked.

### Snapshot
- The key charts side by side: jobs, unemployment, inflation, 10-year yield, curve slope, credit spreads, recession odds, GDP.
- Toggles for 1, 5, 10 years or max, and recession shading on or off. Hover any chart for the exact value.
- Credit card shows one rating at a time (Baa, A, BBB, BB), or the ladder with all three ICE BofA ratings at once.

### Indicators
- Full table: latest reading, recent pace vs the year's pace, the read, next release date.
- Click any row for its chart and a line on why it matters.

### Rates
- Yield curve now vs 3 months and 1 year ago, the Fed funds range, spreads, real yields, inflation expectations.
- Latest Fed statements and speeches.

### Calendar
- When each indicator next updates (next 45 days).

### Benchmarks (beta)
- The firm's benchmark lines rebuilt from ETF total returns, same periods as our report (1 day through 10 years).
- Paste the report's table to see my figures beside the stand-ins and the gap. Stays in my browser; Caerus lines are dropped.
- Funds that are their own benchmark (S&P 500 index, EFA, EMB, EMLC) match the report exactly. Bond and US lines are close. International bonds, EM, REITs and munis run behind because of fund fees and index differences; the Gap view shows by how much.

### Method
- Plain-English scoring rules, market weights, and a health check of which data loaded.

## How it gets to a bias (the part to explain slowly)

**Step 1: score each indicator.**
- Compare its recent pace (roughly the last 3 months) with its pace over the last year.
- Is it speeding up or slowing down against its own trend?
- Scale that gap by how much the indicator normally moves (10 years of history).
- Clearly speeding up = +1. Clearly slowing = −1. Not much change = 0.
- Example: core inflation running hotter over 3 months than over 12 months = inflation heating up.

**Step 2: group them.** Four groups, about five indicators each.
- **Growth:** GDP, industrial production, factory and services surveys, retail sales, consumer sentiment
- **Jobs:** payrolls, unemployment rate, jobless claims, ADP, job openings
- **Inflation:** CPI, core CPI, producer prices, PCE, core PCE
- **Liquidity:** financial conditions, Baa credit spread, real yields, 2-year yield, dollar

**Step 3: each market weighs the groups differently.**
- **Stocks:** like growth and jobs, dislike inflation, like easy conditions.
- **Nasdaq and small caps:** extra sensitive to liquidity.
- **Bonds:** dislike strong growth and especially inflation.
- **Gold:** likes inflation and easy money.
- The weights are my judgement, written down so anyone can challenge them.

**Step 4: combine into a score from −1 to +1.**
- Above 0.2 = bullish. Above 0.5 = very bullish. Same on the downside.

**The regime:** average growth-and-jobs momentum against average inflation momentum. Whichever box it lands in.

## What the numbers mean (they are not percentages)
- The scores are votes and averages. Not a %, not a probability, not a return.
- **+1 / 0 / −1 next to an indicator:** one vote.
  - +1 = clearly moving the way that helps that market
  - −1 = clearly moving the way that hurts it
  - 0 = no clear change
  - The vote is flipped to suit the market. Inflation heating up shows as −1 for stocks.
- **"net +3" on a group:** the votes added up. Net +3 from five indicators could be four up, one down.
- **+0.30 under a market:** the overall score, on a scale from −1.00 to +1.00.
  - +1.00 = every indicator votes in its favour. −1.00 = every one against.
  - +0.30 = the vote leans about a third of the way to fully bullish.
  - Labels: 0.2 and up is bullish, 0.5 and up very bullish. Same below zero. In between is neutral.
- **Numbers on the regime map (like +0.40):** average momentum in "typical moves", meaning how far indicators are speeding up or slowing down against their normal swing. Zero divides the regimes.
- **Anything with a unit is a real reading:** % for rates and inflation, bp for rate changes (1 bp = 0.01 of a percentage point), k or m for jobs.
- **A few readings are index levels with no unit:** Philly Fed surveys (above zero = more firms growing than shrinking), consumer sentiment, financial conditions (zero = average, below = looser), dollar index, VIX.

## How the recession checks work
- **Yield-curve model:** the New York Fed's published model. When 10-year yields fall below 3-month yields (an inverted curve), recession odds rise. Gives a % chance over the next 12 months.
- **Sahm rule:** unemployment rising 0.5 points off its recent low has marked every recession since 1970.
- **Already in recession?** A published statistical model (Chauvet-Piger) on whether we're in one now.
- **GDPNow:** the Atlanta Fed's running estimate of this quarter's growth.

## Credit spreads in one breath
- A spread is the extra yield companies pay over the government. It widens when lenders get nervous.
- **Baa:** lowest rung of investment grade (BBB at S&P). Decades of history, so it's the one the score uses.
- **A, BBB, BB ladder:** shows the cost of each step down in quality. BB to BBB is the line between junk and investment grade.
- The ladder only has 3 years of history on FRED.

## Midterm stat
- The S&P 500 was higher 12 months after all 19 midterms since 1950.
- Average gain around 15%. Some years had sharp drops along the way.
- 19 is a small sample. Rates, earnings and recessions mattered in every one.
- Treat it as a base rate, not a forecast.

## "How this phase played out" notes
- From the Merrill Lynch Investment Clock, a study of which assets led in each growth/inflation mix.
- Roughly: bonds lead in a slowdown, stocks in a recovery, commodities when things overheat, cash in stagflation.
- Describes past averages. Not a call on this cycle.

## Limits (say these before someone asks)
- Macro data only. No valuations, earnings, positioning or price trend.
- Data arrives late and gets revised. GDP especially.
- Scores direction against trend, not surprise against forecasts (FRED doesn't carry forecasts).
- "Good jobs = good for stocks" can fail when the Fed is fighting inflation.
- Market weights and regime notes are judgement and history, not proof.
- It's a framing tool: start a view here, test it elsewhere.

## Likely questions
- **Why not just use the Instagram tool?** Can't see how it scores. Here every rule and source is visible and changeable.
- **How current is it?** As current as FRED. Daily for rates and spreads, weekly for claims, monthly for most, quarterly for GDP.
- **Has it been backtested?** Not yet. Doing it properly needs data as it was first published (ALFRED), not revised data. That's the next step.
- **Can it cover Europe or FX?** FRED's foreign data is thin and late, so I left it out rather than show a confident but weak read.
- **What does it cost?** Nothing. Free API key, free data, runs locally.
