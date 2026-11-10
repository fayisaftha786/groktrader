"""Grok Trader - premium web dashboard for the Grok x Coinbase bot.

Run:  python app.py   then open  http://localhost:8080
Install on phone: Chrome menu -> Add to Home screen.
Live market data (price, 24h change, candles) comes straight from Coinbase
and shows even before the bot is started. Real-money mode can only be
enabled in .env (LIVE=true), never from the page.
"""
import csv
import hmac
import os
import sys
import threading
import time

from flask import Flask, Response, jsonify, request

import bot

app = Flask(__name__)
runner = {"thread": None, "stop": threading.Event()}
state = bot.load_state()
_cache = {"t": 0, "data": None}


PASSWORD = os.getenv("APP_PASSWORD", "")


@app.before_request
def guard():
    """Password-protect everything (username is ignored) when APP_PASSWORD is set."""
    if not PASSWORD or request.path in ("/manifest.json", "/icon.svg"):
        return None
    auth = request.authorization
    if not auth or not hmac.compare_digest((auth.password or "").encode(), PASSWORD.encode()):
        return Response("Login required", 401, {"WWW-Authenticate": 'Basic realm="Grok Trader"'})
    return None


def loop():
    while not runner["stop"].is_set():
        try:
            bot.tick(state)
            bot.save_state(state)
            bot.LAST["error"] = None
        except Exception as e:
            bot.LAST["error"] = str(e)[:200]
        runner["stop"].wait(bot.LOOP_SECONDS)


def start_bot():
    t = runner["thread"]
    if not (t and t.is_alive()):
        runner["stop"].clear()
        runner["thread"] = threading.Thread(target=loop, daemon=True)
        runner["thread"].start()


@app.post("/start")
def start():
    start_bot()
    return jsonify(ok=True)


@app.post("/stop")
def stop():
    runner["stop"].set()
    return jsonify(ok=True)


@app.get("/api/market")
def market():
    """Real Coinbase data: live price, 24h change, recent candles (cached 4s)."""
    if time.time() - _cache["t"] < 4 and _cache["data"]:
        return jsonify(_cache["data"])
    try:
        info = bot.cb.get_public_product(bot.PRODUCT)
        candles = bot.get_candles()
        data = dict(ok=True, price=float(bot.g(info, "price")),
                    change24h=float(bot.g(info, "price_percentage_change_24h") or 0),
                    candles=[[c["t"], c["c"]] for c in candles],
                    high=max(c["h"] for c in candles), low=min(c["l"] for c in candles),
                    updated=time.strftime("%H:%M:%S"))
        _cache.update(t=time.time(), data=data)
        return jsonify(data)
    except Exception as e:
        return jsonify(ok=False, error=str(e)[:200])


@app.get("/api/status")
def status():
    t = runner["thread"]
    price = bot.LAST["price"]
    equity = None
    if not bot.LIVE:
        px = price or (_cache["data"] or {}).get("price")
        if px:
            equity = state["paper_usd"] + state["paper_base"] * px
    px = (_cache["data"] or {}).get("price") or price
    pnl_pct = None
    if state.get("entry_price") and px:
        pnl_pct = round((px / state["entry_price"] - 1) * 100, 2)
    trades = []
    if os.path.exists(bot.LOG_FILE):
        with open(bot.LOG_FILE) as f:
            trades = list(csv.DictReader(f))[-30:][::-1]
    return jsonify(running=bool(t and t.is_alive() and not runner["stop"].is_set()),
                   mode="LIVE" if bot.LIVE else "PAPER", product=bot.PRODUCT,
                   last=bot.LAST, state=state, equity=equity, pnl_pct=pnl_pct,
                   start_usd=bot.PAPER_START_USD,
                   cfg=dict(trade_usd=bot.TRADE_USD, sl=bot.STOP_LOSS_PCT, tp=bot.TAKE_PROFIT_PCT,
                            every=bot.LOOP_SECONDS, max_trades=bot.MAX_TRADES_PER_DAY,
                            min_conf=bot.MIN_CONFIDENCE),
                   trades=trades)


ICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="#34d399"/><stop offset="1" stop-color="#22d3ee"/></linearGradient></defs>'
        '<rect width="512" height="512" rx="115" fill="#0a0c10"/>'
        '<path d="M92 346l92-112 72 62 112-152" fill="none" stroke="url(#g)" stroke-width="38" stroke-linecap="round" stroke-linejoin="round"/>'
        '<circle cx="368" cy="132" r="28" fill="url(#g)"/></svg>')


@app.get("/icon.svg")
def icon():
    return Response(ICON, mimetype="image/svg+xml")


@app.get("/manifest.json")
def manifest():
    return jsonify(name="Grok Trader", short_name="Grok Trader", start_url="/", display="standalone",
                   background_color="#0a0c10", theme_color="#0a0c10",
                   icons=[{"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any"}])


PAGE = """<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Grok Trader</title>
<link rel=manifest href=/manifest.json><link rel=icon href=/icon.svg>
<meta name=theme-color content="#0a0c10"><meta name=apple-mobile-web-app-capable content=yes>
<style>
:root{--bg:#0a0c10;--card:rgba(255,255,255,.045);--bd:rgba(255,255,255,.08);--tx:#f1f3f8;--mut:#7d8597;
--g:#34d399;--r:#f87171;--y:#fbbf24;--c:#22d3ee}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{margin:0;font:15px/1.4 -apple-system,Inter,system-ui,sans-serif;color:var(--tx);min-height:100vh;
background:radial-gradient(900px 500px at 85% -10%,rgba(34,211,238,.13),transparent),
radial-gradient(700px 500px at -10% 10%,rgba(52,211,153,.10),transparent),var(--bg);
padding:calc(14px + env(safe-area-inset-top)) 14px calc(30px + env(safe-area-inset-bottom));max-width:560px;margin:auto}
.top{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px}
.brand{display:flex;gap:10px;align-items:center;font-weight:700;font-size:17px;letter-spacing:.2px}
.brand img{width:30px;height:30px;border-radius:9px}
.pill{display:inline-flex;align-items:center;gap:6px;padding:5px 11px;border-radius:99px;font-size:11.5px;font-weight:700;
letter-spacing:.6px;border:1px solid var(--bd);background:var(--card)}
.paper{color:#93c5fd}.live{color:#fff;background:linear-gradient(135deg,#dc2626,#f97316);border:0}
.dot{width:7px;height:7px;border-radius:50%;background:var(--g);box-shadow:0 0 0 0 rgba(52,211,153,.7);animation:p 1.6s infinite}
.off{background:var(--mut);animation:none}
@keyframes p{70%{box-shadow:0 0 0 8px rgba(52,211,153,0)}100%{box-shadow:0 0 0 0 rgba(52,211,153,0)}}
.card{background:var(--card);border:1px solid var(--bd);border-radius:20px;padding:16px;margin-bottom:12px;
backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px)}
.lbl{color:var(--mut);font-size:12px;letter-spacing:.5px;text-transform:uppercase;font-weight:600}
.price{font-size:38px;font-weight:800;letter-spacing:-1px;font-variant-numeric:tabular-nums;margin:2px 0}
.chg{font-weight:700;font-size:14px}.up{color:var(--g)}.dn{color:var(--r)}.hold{color:var(--y)}
.row{display:flex;justify-content:space-between;align-items:flex-end;gap:10px}
svg.chart{width:100%;height:auto;display:block;margin-top:8px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.stat b{display:block;font-size:20px;font-weight:700;margin-top:3px;font-variant-numeric:tabular-nums}
.act{font-size:30px;font-weight:800;letter-spacing:-.5px}
.bar{height:6px;border-radius:9px;background:rgba(255,255,255,.08);margin:10px 0 8px;overflow:hidden}
.bar i{display:block;height:100%;border-radius:9px;background:linear-gradient(90deg,var(--c),var(--g));transition:width .6s}
.why{color:#b6bdcc;font-size:13.5px}
.btns{display:grid;grid-template-columns:1.4fr 1fr;gap:10px}
button{border:0;border-radius:14px;padding:14px;font-size:15px;font-weight:700;color:#06210f;cursor:pointer;transition:transform .1s}
button:active{transform:scale(.97)}
.go{background:linear-gradient(135deg,#34d399,#22d3ee)}.no{background:rgba(248,113,113,.14);color:var(--r);border:1px solid rgba(248,113,113,.3)}
.cfg{color:var(--mut);font-size:12px;margin-top:12px;line-height:1.7}
.t{display:flex;justify-content:space-between;align-items:center;padding:10px 0;border-bottom:1px solid var(--bd)}
.t:last-child{border:0}.tag{font-weight:800;font-size:11px;padding:3px 9px;border-radius:8px;margin-right:9px}
.tag.BUY{background:rgba(52,211,153,.15);color:var(--g)}.tag.SELL{background:rgba(248,113,113,.15);color:var(--r)}
.small{font-size:12px;color:var(--mut)}.err{color:var(--r);font-size:12.5px;margin-top:6px}
</style></head><body>
<div class=top>
 <div class=brand><img src=/icon.svg alt=""><span>Grok Trader</span></div>
 <span id=mode class="pill paper">PAPER</span>
</div>

<div class=card>
 <div class=row><div><div class=lbl id=prod>BTC-USD</div><div class=price id=price>--</div>
  <div class=chg id=chg>&nbsp;</div></div>
  <div class=small style="text-align:right"><span class=pill><i class=dot id=dot></i><span id=upd>connecting</span></span></div></div>
 <svg class=chart id=chart viewBox="0 0 600 230" preserveAspectRatio="none"></svg>
 <div class=row style="margin-top:6px"><span class=small id=lo></span><span class=small id=hi></span></div>
</div>

<div class=grid>
 <div class="card stat"><div class=lbl>Portfolio</div><b id=eq>--</b><span class=small id=eqs>paper account</span></div>
 <div class="card stat"><div class=lbl>Open P/L</div><b id=pnl>Flat</b><span class=small id=pos>no position</span></div>
</div>

<div class=card>
 <div class=row><div class=lbl>Grok's call</div><div class=small id=lt></div></div>
 <div class=act id=act>Waiting</div>
 <div class=bar><i id=conf style="width:0%"></i></div>
 <div class=why id=why>Press Start to let Grok analyze the market.</div>
 <div class=err id=err></div>
</div>

<div class=card>
 <div class=btns><button class=go onclick="post('/start')">&#9654; Start bot</button>
 <button class=no onclick="post('/stop')">Stop</button></div>
 <div class=cfg id=cfg></div>
</div>

<div class=card><div class=lbl style="margin-bottom:4px">Trade history</div><div id=tr class=small>No trades yet</div></div>

<script>
const $=id=>document.getElementById(id);
const fmt=(n,d=2)=>Number(n).toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d});
let trades=[];
async function post(u){await fetch(u,{method:'POST'});status()}

function chart(c){
 if(!c||c.length<2)return;
 const W=600,H=230,p=10,v=c.map(x=>x[1]),mn=Math.min(...v),mx=Math.max(...v),n=v.length;
 const X=i=>p+i*(W-2*p)/(n-1),Y=x=>H-p-(x-mn)/((mx-mn)||1)*(H-2*p-14);
 const up=v[n-1]>=v[0],col=up?'#34d399':'#f87171';
 let d='M'+X(0)+','+Y(v[0]);for(let i=1;i<n;i++){const x0=X(i-1),x1=X(i),y0=Y(v[i-1]),y1=Y(v[i]),m=(x0+x1)/2;d+=' C'+m+','+y0+' '+m+','+y1+' '+x1+','+y1}
 let marks='';
 trades.forEach(t=>{const ts=Date.parse(t.time_utc)/1000;let k=-1,b=1e12;c.forEach((q,i)=>{const dd=Math.abs(q[0]-ts);if(dd<b){b=dd;k=i}});
  if(k>=0&&b<7200){marks+=`<circle cx="${X(k)}" cy="${Y(+t.price>mx?mx:+t.price<mn?mn:+t.price)}" r="7" fill="${t.side=='BUY'?'#34d399':'#f87171'}" stroke="#0a0c10" stroke-width="3"/>`}});
 $('chart').innerHTML=`<defs><linearGradient id=a x1=0 y1=0 x2=0 y2=1><stop offset=0 stop-color="${col}" stop-opacity=".35"/><stop offset=1 stop-color="${col}" stop-opacity="0"/></linearGradient></defs>
 <path d="${d} L${X(n-1)},${H} L${X(0)},${H} Z" fill="url(#a)"/><path d="${d}" fill="none" stroke="${col}" stroke-width="3" stroke-linecap="round"/>
 ${marks}<circle cx="${X(n-1)}" cy="${Y(v[n-1])}" r="5" fill="${col}"/><circle cx="${X(n-1)}" cy="${Y(v[n-1])}" r="11" fill="${col}" opacity=".25"/>`;
}

async function market(){
 try{const d=await (await fetch('/api/market')).json();
  if(!d.ok){$('upd').textContent='offline';$('dot').className='dot off';return}
  $('price').textContent='$'+fmt(d.price);
  const up=d.change24h>=0;$('chg').textContent=(up?'\\u25B2 ':'\\u25BC ')+fmt(Math.abs(d.change24h))+'% 24h';$('chg').className='chg '+(up?'up':'dn');
  $('upd').textContent='LIVE '+d.updated;$('dot').className='dot';
  $('lo').textContent='Low $'+fmt(d.low,0);$('hi').textContent='High $'+fmt(d.high,0);
  chart(d.candles);
 }catch(e){$('upd').textContent='offline';$('dot').className='dot off'}
}

async function status(){
 try{const d=await (await fetch('/api/status')).json();
  $('prod').textContent=d.product;
  $('mode').textContent=d.mode;$('mode').className='pill '+d.mode.toLowerCase();
  trades=d.trades;
  if(d.equity!=null){$('eq').textContent='$'+fmt(d.equity);const g=d.equity-d.start_usd;
   $('eqs').textContent=(g>=0?'+':'')+fmt(g)+' vs start';$('eqs').className='small '+(g>=0?'up':'dn')}
  else{$('eq').textContent='Live account';$('eqs').textContent='see Coinbase'}
  if(d.pnl_pct!=null){$('pnl').textContent=(d.pnl_pct>0?'+':'')+d.pnl_pct+'%';$('pnl').className=d.pnl_pct>=0?'up':'dn';$('pos').textContent='entry $'+fmt(d.state.entry_price,0)}
  else{$('pnl').textContent='Flat';$('pnl').className='';$('pos').textContent='no position'}
  const l=d.last;
  if(l.action){$('act').textContent=l.action;$('act').className='act '+(l.action=='BUY'?'up':l.action=='SELL'?'dn':'hold');
   $('conf').style.width=Math.round(l.conf*100)+'%';$('why').textContent=Math.round(l.conf*100)+'% confidence - '+l.reason;$('lt').textContent=l.time}
  $('err').textContent=l.error||'';
  const c=d.cfg;$('cfg').innerHTML=(d.running?'<b class=up>Bot running</b>':'<b>Bot stopped</b>')+`<br>$${c.trade_usd} per trade - stop-loss ${c.sl}% - take-profit ${c.tp}%<br>checks every ${c.every/60} min - max ${c.max_trades} trades/day - min confidence ${Math.round(c.min_conf*100)}%`;
  if(d.trades.length)$('tr').innerHTML=d.trades.map(t=>`<div class=t><div><span class="tag ${t.side}">${t.side}</span>${t.mode}</div>
   <div style="text-align:right"><b>$${fmt(t.price,0)}</b><div class=small>${t.time_utc.slice(5,16).replace('T',' ')} UTC - $${fmt(t.usd)}</div></div></div>`).join('');
 }catch(e){}
}
market();status();setInterval(market,5000);setInterval(status,8000);
</script></body></html>"""


@app.get("/")
def index():
    return PAGE


if __name__ == "__main__":
    if bot.LIVE and not PASSWORD:
        sys.exit("Refusing to start in LIVE mode without APP_PASSWORD set in .env")
    if os.getenv("AUTO_START", "false").lower() == "true":
        start_bot()
    print(f"Dashboard: http://localhost:8080  (mode: {'LIVE' if bot.LIVE else 'PAPER'})")
    app.run(host="0.0.0.0", port=8080)
