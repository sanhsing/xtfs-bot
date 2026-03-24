"""
XTFS Bot v5.3 — 智能路由版
設計：@織明 | 2026-03-24
"""
import json, os, time, requests, threading
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=8))
TOKEN   = os.environ.get("TELEGRAM_TOKEN", "8698109729:AAEmP1hKZt_VnB4XRvzNy1L13XonzQYgOB0")
API     = f"https://api.telegram.org/bot{TOKEN}"
KEYS = {
    "deepseek":  os.environ.get("DEEPSEEK_API_KEY",  "sk-313ab8b056e64cdea7ddbf69c55878d8"),
    "gemini":    os.environ.get("GEMINI_API_KEY",    "AIzaSyAbVsML4msADy44d_7AvTHYB6Jnx0F7BAQ"),
    "openai":    os.environ.get("OPENAI_API_KEY",    "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"),
    "anthropic": os.environ.get("ANTHROPIC_API_KEY", "sk-ant-api03-HEACZHxjvmfs23kguS7ZbhO_xZI9NsXl7Ok6x9_Avapg_45wehQU92rgJcyqwRsIOp0QyVeUTEOM0dXC_wxVZQ-x4CanAAA"),
}
MAX_MEM = 100
TOWER_CFG = {
    "F": {"e":"⚙️","n":"F塔·DeepSeek","p":"你是XTFS的F塔（邏輯塔）。專注結構化推理、程式碼生成。精確、簡潔。"},
    "T": {"e":"🌐","n":"T塔·Gemini",  "p":"你是XTFS的T塔（感知塔）。專注廣域掃描、事實查核、即時資訊。"},
    "S": {"e":"🔮","n":"S塔·Claude",  "p":"你是XTFS的S塔（秩序塔）。專注長文分析、架構設計、哲學推演。"},
    "X": {"e":"⚖️","n":"X塔·ChatGPT","p":"你是XTFS的X塔（治理塔）。專注多角度決策、治理框架、風險評估。"},
}
WORKFLOWS = {
    "research": [("T","廣域蒐集，列出要點：{input}"),("F","分析提取核心邏輯：{input}"),("S","整合為結構化報告：{input}")],
    "decision": [("S","深度分析各面向：{input}"),("X","治理審查評估風險：{input}"),("F","制定執行計劃：{input}")],
    "create":   [("S","創作初稿：{input}"),("F","優化去冗余：{input}"),("X","最終審核：{input}")],
    "verify":   [("F","邏輯驗證找漏洞：{input}"),("T","事實查核：{input}"),("X","最終裁決：{input}")],
    "standard": [("X","拆解子任務：{input}"),("T","擴展資訊：{input}"),("F","整合分析：{input}"),("S","審定優化：{input}")],
}
QUICK_PROMPT = """你是XTFS塔數判斷器。只回答1/2/3/4。
1塔：問候/寫信/簡單翻譯/日常對話/基礎知識
2塔：需要決策審查但不需實作（投資建議/風險評估/策略分析）
3塔：需要程式碼/技術實作/複雜分析（架構設計/系統/算法）
4塔：需要即時網路資訊（今天/現在/最新的新聞/匯率/股價/天氣）
只回答數字。"""
WORKFLOW_PROMPT = """判斷任務最適合的工作流。只回答：research/decision/create/verify/standard
research：蒐集+分析+整合 decision：分析+審查+執行 create：起草+優化+審核 verify：邏輯+事實+裁決 standard：其他
只回答一個詞。"""

def quick_route(task):
    try:
        r=requests.post("https://api.deepseek.com/chat/completions",
            headers={"Authorization":f"Bearer {KEYS['deepseek']}","Content-Type":"application/json"},
            json={"model":"deepseek-chat","messages":[{"role":"system","content":QUICK_PROMPT},{"role":"user","content":task}],"max_tokens":5,"temperature":0},timeout=8)
        ans=r.json()["choices"][0]["message"]["content"].strip()
        tc=int(next((c for c in ans if c in "1234"),"3"))
    except: tc=_doe(task)
    final_tc=max(tc,_doe(task))
    if final_tc==1: return {"mode":"single","tower":_best(task),"tc":1}
    wf=_wf(task)
    return {"mode":"multi","workflow":wf,"steps":_filter(WORKFLOWS.get(wf,WORKFLOWS["standard"]),final_tc),"tc":final_tc}

def _doe(task):
    t=task.lower()
    rt=8.0 if any(k in t for k in ["今天","最新","現在","即時","新聞","匯率","天氣","股市","cpi"]) else 1.0
    cp=7.0 if any(k in t for k in ["程式","分析","架構","設計","算法","系統","實作"]) else 2.0
    gv=7.0 if any(k in t for k in ["決策","風險","治理","建議","策略","投資"]) else 1.0
    vr=6.0 if any(k in t for k in ["驗證","查核","比較","評估","確認"]) else 1.0
    total=rt*0.35+cp*0.30+gv*0.15+vr*0.20
    if total<2.0: return 1
    elif total<3.5 and gv<5: return 2
    elif total<5.0 or gv>=5: return 3
    elif rt>5: return 4
    return 3

def _best(task):
    t=task.lower()
    if any(k in t for k in ["程式","python","算法","bug"]): return "F"
    if any(k in t for k in ["今天","最新","現在","新聞","匯率"]): return "T"
    if any(k in t for k in ["決策","風險","建議","策略"]): return "X"
    return "S"

def _wf(task):
    try:
        r=requests.post("https://api.deepseek.com/chat/completions",
            headers={"Authorization":f"Bearer {KEYS['deepseek']}","Content-Type":"application/json"},
            json={"model":"deepseek-chat","messages":[{"role":"system","content":WORKFLOW_PROMPT},{"role":"user","content":task}],"max_tokens":10,"temperature":0},timeout=8)
        ans=r.json()["choices"][0]["message"]["content"].strip().lower()
        return ans if ans in WORKFLOWS else "standard"
    except: return "standard"

def _filter(steps,tc):
    if tc==2: return [s for s in steps if s[0] in ("S","X")]
    if tc==3: return [s for s in steps if s[0]!="T"]
    return steps

def call_tower(tower,system,history,msg,timeout=45):
    try:
        if tower=="F":
            r=requests.post("https://api.deepseek.com/chat/completions",headers={"Authorization":f"Bearer {KEYS['deepseek']}","Content-Type":"application/json"},json={"model":"deepseek-chat","messages":[{"role":"system","content":system}]+history+[{"role":"user","content":msg}],"max_tokens":1000},timeout=timeout)
            d=r.json(); return d["choices"][0]["message"]["content"],d.get("usage",{}).get("total_tokens",0)
        elif tower=="T":
            url=f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={KEYS['gemini']}"
            contents=[{"role":"user" if m["role"]=="user" else "model","parts":[{"text":m["content"]}]} for m in history]
            contents.append({"role":"user","parts":[{"text":system+"\n\n"+msg}]})
            r=requests.post(url,json={"contents":contents},timeout=timeout); d=r.json()
            return d["candidates"][0]["content"]["parts"][0]["text"],d.get("usageMetadata",{}).get("totalTokenCount",0)
        elif tower=="S":
            msgs=history+[{"role":"user","content":msg}]
            r=requests.post("https://api.anthropic.com/v1/messages",headers={"x-api-key":KEYS["anthropic"],"anthropic-version":"2023-06-01","content-type":"application/json"},json={"model":"claude-3-5-sonnet-20241022","max_tokens":1024,"system":system,"messages":msgs},timeout=timeout)
            d=r.json(); return d["content"][0]["text"],d.get("usage",{}).get("input_tokens",0)+d.get("usage",{}).get("output_tokens",0)
        elif tower=="X":
            r=requests.post("https://api.openai.com/v1/chat/completions",headers={"Authorization":f"Bearer {KEYS['openai']}","Content-Type":"application/json"},json={"model":"gpt-4o-mini","messages":[{"role":"system","content":system}]+history+[{"role":"user","content":msg}],"max_tokens":1000},timeout=timeout)
            d=r.json(); return d["choices"][0]["message"]["content"],d.get("usage",{}).get("total_tokens",0)
    except Exception as e: return f"[{tower}塔錯誤] {str(e)[:80]}",0

memory={}; last_route={}; route_logs={}
def get_hist(cid,n=30): return memory.get(str(cid),[])[-n*2:]
def add_hist(cid,role,content):
    k=str(cid)
    if k not in memory: memory[k]=[]
    memory[k].append({"role":role,"content":content}); memory[k]=memory[k][-MAX_MEM*2:]
def log_route(cid,task,plan):
    k=str(cid)
    if k not in route_logs: route_logs[k]=[]
    route_logs[k].append({"task":task,"plan":plan}); route_logs[k]=route_logs[k][-50:]
    last_route[str(cid)]=plan

def send(cid,text,rid=None,kb=None):
    for i in range(0,len(text),4000):
        p={"chat_id":cid,"text":text[i:i+4000],"parse_mode":"Markdown"}
        if rid and i==0: p["reply_to_message_id"]=rid
        if kb and i+4000>=len(text): p["reply_markup"]=kb
        try: requests.post(f"{API}/sendMessage",json=p,timeout=10)
        except: pass

def execute(cid,task,plan,mid):
    st=time.time(); total_tokens=0
    if plan["mode"]=="single":
        tower=plan["tower"]; cfg=TOWER_CFG[tower]
        out,tk=call_tower(tower,cfg["p"],get_hist(cid),task)
        total_tokens+=tk; elapsed=time.time()-st
        add_hist(cid,"user",task); add_hist(cid,"assistant",out)
        fb={"inline_keyboard":[[{"text":"👍","callback_data":f"fb_ok_{mid}"},{"text":"👎","callback_data":f"fb_bad_{mid}"},{"text":"🗑","callback_data":"clear"}]]}
        send(cid,f"{cfg['e']} *{cfg['n']}*\n\n{out}\n\n---\n{elapsed:.1f}s | {tk}tk",rid=mid,kb=fb)
    else:
        steps=plan["steps"]; tc=plan["tc"]; wf=plan.get("workflow","standard")
        send(cid,f"🔄 *{tc}塔協作 · {wf}*\n\n共{len(steps)}步，執行中...")
        current=task; outputs=[]
        for i,(tower,tmpl) in enumerate(steps,1):
            cfg=TOWER_CFG[tower]
            send(cid,f"⏳ Step {i}/{len(steps)} — {cfg['e']} {cfg['n']}...")
            out,tk=call_tower(tower,cfg["p"],[],tmpl.format(input=current))
            total_tokens+=tk; outputs.append(f"{cfg['e']} *{cfg['n']}*\n{out}"); current=out
        elapsed=time.time()-st
        add_hist(cid,"user",task); add_hist(cid,"assistant",current)
        fb={"inline_keyboard":[[{"text":"👍路由正確","callback_data":f"fb_ok_{mid}"},{"text":"👎路由錯誤","callback_data":f"fb_bad_{mid}"}]]}
        send(cid,"\n\n---\n".join(outputs)+f"\n\n---\n⏱ {elapsed:.1f}s | {total_tokens}tk",kb=fb)

def handle_msg(m):
    cid=m["chat"]["id"]; txt=m.get("text","").strip(); mid=m.get("message_id"); u=m.get("from",{})
    if not txt: return
    k=str(cid)
    if txt=="/start":
        kb={"inline_keyboard":[[{"text":"⚙️F邏輯","callback_data":"mode_F"},{"text":"🌐T事實","callback_data":"mode_T"}],[{"text":"🔮S秩序","callback_data":"mode_S"},{"text":"⚖️X治理","callback_data":"mode_X"}],[{"text":"🤖智能路由","callback_data":"mode_AUTO"},{"text":"🗑清除","callback_data":"clear"}]]}
        un=f"@{u.get('username')}" if u.get("username") else u.get("first_name","User")
        send(cid,f"*XTFS Bot v5.3 智能路由版* 🚀\n\n歡迎 {un}！\n\n🤖 智能判斷1-4塔\n⚙️F·DeepSeek 🌐T·Gemini 🔮S·Claude ⚖️X·ChatGPT\n\n`/route` `/fb` `/stats` `/clear`\n\n直接發問！",kb=kb); return
    if txt=="/clear":
        memory.pop(k,None); route_logs.pop(k,None); last_route.pop(k,None); send(cid,"✅ 已清除"); return
    if txt=="/stats":
        logs=route_logs.get(k,[])
        if not logs: send(cid,"📊 還沒有記錄"); return
        dist={}
        for l in logs: dist[l["plan"].get("tc",0)]=dist.get(l["plan"].get("tc",0),0)+1
        msg="📊 *路由統計*\n\n"
        for tc,cnt in sorted(dist.items()): msg+=f"{tc}塔：{'█'*cnt} {cnt}次\n"
        send(cid,msg); return
    if txt.startswith("/route "):
        task=txt[7:].strip()
        if not task: send(cid,"用法：`/route 任務描述`"); return
        send(cid,"🔄 分析路由中...")
        plan=quick_route(task); tc=plan["tc"]
        if plan["mode"]=="single":
            cfg=TOWER_CFG[plan["tower"]]; detail=f"→ {cfg['e']} {cfg['n']}"
        else:
            steps=plan.get("steps",[]); towers=" → ".join(f"{TOWER_CFG[s[0]]['e']}{s[0]}塔" for s in steps)
            detail=f"→ {plan.get('workflow','')} 工作流\n{towers}"
        send(cid,f"📋 *路由分析*\n\n任務：{task}\n塔數：{tc}塔\n{detail}\n\n發 `/fb {tc}` 確認正確塔數")
        log_route(cid,task,plan); return
    if txt.startswith("/fb"):
        parts=txt.split()
        if len(parts)<2 or not parts[1].isdigit(): send(cid,"用法：`/fb 3`"); return
        correct=int(parts[1]); last=last_route.get(k)
        if not last: send(cid,"❌ 找不到上次路由"); return
        final=last.get("tc",0)
        if final==correct: send(cid,"✅ 路由正確！感謝確認。")
        else:
            diff=correct-final; d="低估" if diff>0 else "高估"
            send(cid,f"📝 已記錄：應為{correct}塔，路由{d}{abs(diff)}塔。感謝！"); return
    forced=None
    for cmd,tower in [("/f ","F"),("/t ","T"),("/s ","S"),("/x ","X"),("/logic ","F"),("/fact ","T"),("/claude ","S"),("/govern ","X")]:
        if txt.startswith(cmd): forced,txt=tower,txt[len(cmd):].strip(); break
    if not txt: return
    if forced: plan={"mode":"single","tower":forced,"tc":1}
    else:
        send(cid,"🔄 智能路由分析中..."); plan=quick_route(txt)
    log_route(cid,txt,plan)
    threading.Thread(target=execute,args=(cid,txt,plan,mid),daemon=True).start()

def handle_cb(q):
    cid=q["message"]["chat"]["id"]; d=q.get("data",""); qid=q.get("id")
    try: requests.post(f"{API}/answerCallbackQuery",json={"callback_query_id":qid},timeout=5)
    except: pass
    if d.startswith("mode_"):
        t=d[5:]
        if t=="AUTO": send(cid,"🤖 *智能路由* 已啟用！直接發問。")
        else:
            cfg=TOWER_CFG.get(t,{}); send(cid,f"{cfg.get('e','')} *{cfg.get('n','')}* 就緒！直接發問。")
    elif d=="clear":
        k=str(cid); memory.pop(k,None); route_logs.pop(k,None); last_route.pop(k,None); send(cid,"✅ 已清除")
    elif d.startswith("fb_ok_"): send(cid,"✅ 路由正確，感謝！")
    elif d.startswith("fb_bad_"): send(cid,"📝 請用 `/fb {塔數}` 告訴我正確塔數。")

def run():
    offset=0; print(f"✅ XTFS Bot v5.3 啟動")
    while True:
        try:
            r=requests.get(f"{API}/getUpdates",params={"offset":offset,"timeout":30},timeout=35)
            for u in r.json().get("result",[]):
                offset=u["update_id"]+1
                if "message" in u: threading.Thread(target=handle_msg,args=(u["message"],),daemon=True).start()
                elif "callback_query" in u: handle_cb(u["callback_query"])
        except Exception as e: print(f"❌ {e}"); time.sleep(3)

if __name__=="__main__": run()
