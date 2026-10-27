import os, sys, io, requests
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

API = os.environ["TWELVE_DATA_API_KEY"]
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT = os.environ["TELEGRAM_CHAT_ID"]
PKT = ZoneInfo("Asia/Karachi")

def candles(interval, n=150):
    r=requests.get("https://api.twelvedata.com/time_series",params={
        "symbol":"XAU/USD","interval":interval,"outputsize":n,
        "timezone":"UTC","apikey":API,"format":"JSON"},timeout=30)
    r.raise_for_status()
    j=r.json()
    if j.get("status")=="error" or "values" not in j:
        raise RuntimeError(f"{interval} market data unavailable: {j.get('message', str(j)[:180])}")
    vals=[]
    for v in j["values"]:
        t=datetime.fromisoformat(v["datetime"]).replace(tzinfo=timezone.utc)
        vals.append({"t":t,**{k:float(v[k]) for k in ("open","high","low","close")}})
    vals.sort(key=lambda v:v["t"])
    minutes=60 if interval=="1h" else 15
    now=datetime.now(timezone.utc)
    vals=[v for v in vals if v["t"]+timedelta(minutes=minutes)<=now]
    if len(vals)<55: raise RuntimeError(f"Not enough completed {interval} candles")
    if now-vals[-1]["t"]>timedelta(minutes=minutes+35):
        raise RuntimeError(f"Stale {interval} candles; latest {vals[-1]['t']}")
    return vals

def ema(prices,n):
    v=prices[0]; alpha=2/(n+1)
    for p in prices[1:]: v=alpha*p+(1-alpha)*v
    return v

def atr(rows,n=14):
    tr=[]
    for i in range(1,len(rows)):
        a,b=rows[i],rows[i-1]
        tr.append(max(a["high"]-a["low"],abs(a["high"]-b["close"]),abs(a["low"]-b["close"])))
    return sum(tr[-n:])/n

def send_text(msg):
    r=requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
       data={"chat_id":CHAT,"text":msg},timeout=30)
    r.raise_for_status()
    if not r.json().get("ok"):raise RuntimeError("Telegram delivery failed")

def main():
    h=candles("1h"); m=candles("15min")
    close=h[-1]["close"]
    h20=ema([v["close"] for v in h],20)
    h50=ema([v["close"] for v in h],50)
    m20=ema([v["close"] for v in m],20)
    m50=ema([v["close"] for v in m],50)
    direction="BUY" if h20>=h50 else "SELL"
    aligned=(m20>=m50)==(direction=="BUY")
    volatility=atr(h)
    if volatility<=0: raise RuntimeError("Invalid ATR")
    entry=close
    # Calculated reference levels, NOT broker-executable quotes.
    sl=entry-volatility*1.5 if direction=="BUY" else entry+volatility*1.5
    tp=entry+volatility*3 if direction=="BUY" else entry-volatility*3
    stamp=(h[-1]["t"]+timedelta(hours=1)).astimezone(PKT).strftime("%d %b %Y %I:%M %p PKT")
    msg=(f"XAU/USD H1 | {stamp}\nDirection: {direction}\n"
         f"H1 EMA20/50: {h20:.2f} / {h50:.2f}\n"
         f"M15 confirmation: {'Aligned' if aligned else 'NOT aligned'}\n"
         f"Last closed H1 price: {entry:.2f}\n"
         f"Illustrative entry: {entry:.2f}\n"
         f"ATR-based SL: {sl:.2f}\nATR-based TP: {tp:.2f}\n"
         "These are calculated reference levels, not live executable quotes. "
         "No independently verified SMC OB/FVG, DXY, US10Y or news confirmation. "
         "Do not place a trade solely from this alert.")
    fig,ax=plt.subplots(figsize=(11,5.5))
    recent=h[-45:]
    for i,v in enumerate(recent):
        up=v["close"]>=v["open"]
        color="#12805c" if up else "#c44545"
        ax.vlines(i,v["low"],v["high"],color=color,linewidth=1)
        ax.add_patch(Rectangle((i-.32,min(v["open"],v["close"])),.64,
            max(abs(v["close"]-v["open"]),.01),color=color))
    for y,label,c in [(entry,"Last close","#2463eb"),(sl,"SL","#d94646"),(tp,"TP","#168a61")]:
        ax.axhline(y,linestyle="--",color=c,label=f"{label}: {y:.2f}")
    ax.set_title(f"XAU/USD H1 | {direction} bias | {stamp}")
    ax.set_ylabel("USD per troy ounce")
    ax.set_xticks(range(0,len(recent),8),
       [recent[i]["t"].strftime("%d %b %H:%M") for i in range(0,len(recent),8)])
    ax.legend(loc="best"); ax.grid(alpha=.15);fig.tight_layout()
    b=io.BytesIO();fig.savefig(b,format="png",dpi=150);plt.close(fig);b.seek(0)
    r=requests.post(f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
        data={"chat_id":CHAT,"caption":msg[:1024]},
        files={"photo":("xau_h1.png",b,"image/png")},timeout=40)
    r.raise_for_status()
    if not r.json().get("ok"):raise RuntimeError("Telegram photo delivery failed")

if __name__=="__main__":
    try: main()
    except Exception as exc:
        # Avoid disclosing API secrets in logs or messages.
        print("Signal not sent:",type(exc).__name__,str(exc).replace(API,"[REDACTED]").replace(TOKEN,"[REDACTED]"))
        sys.exit(1)
