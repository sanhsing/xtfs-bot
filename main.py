
import json, time, requests, threading

TOKEN = "8698109729:AAEmP1hKZt_VnB4XRvzNy1L13XonzQYgOB0"
API = f"https://api.telegram.org/bot{TOKEN}"

KEY_GROQ   = os.environ.get("GROQ_API_KEY", "")
KEY_GEMINI = os.environ.get("GEMINI_API_KEY", "")
KEY_OAI    = os.environ.get("OPENAI_API_KEY", "")
KEY_ANT    = os.environ.get("ANTHROPIC_API_KEY", "")

TOWERS = {
    "F":{"n":"F塔·Groq","e":"⚙️","p":"你是XTFS的F塔（邏輯塔）。專注結構化推理、程式碼生成。精確、簡潔。"},
    "T":{"n":"T塔·Gemini","e":"🌐","p":"你是XTFS的T塔（感知塔）。專注廣域掃描、事實查核。"},
    "S":{"n":"S塔·Claude","e":"🔮","p":"你是XTFS的S塔（秩序塔）。專注長文分析、架構設計。"},
    "X":{"n":"X塔·ChatGPT","e":"⚖️","p":"你是XTFS的X塔（治理塔）。專注決策框架、風險評估。"},
}

memory = {}  # 簡單記憶體存儲

def call_f(sys,hist,msg):
    msgs=[{"role":"system","content":sys}]+hist[-60:]+[{"role":"user","content":msg}]
    r=requests.post("https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization":f"Bearer {KEY_GROQ}","Content-Type":"application/json"},
        json={"model":"llama-3.3-70b-versatile","messages":msgs,"max_tokens":800},timeout=30)
    d=r.json(); return d["choices"][0]["message"]["content"],d.get("usage",{}).get("total_tokens",0)

def call_t(sys,hist,msg):
    url=f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={KEY_GEMINI}"
    contents=[]
    for m in hist[-60:]:
        contents.append({"role":"user" if m["role"]=="user" else "model","parts":[{"text":m["content"]}]})
    contents.append({"role":"user","parts":[{"text":sys+"\n\n"+msg}]})
    r=requests.post(url,json={"contents":contents},timeout=30); d=r.json()
    try: return d["candidates"][0]["content"]["parts"][0]["text"],0
    except: return f"T塔錯誤: {d.get('error',{}).get('message','?')}", 0

def call_s(sys,hist,msg):
    msgs=hist[-60:]+[{"role":"user","content":msg}]
    r=requests.post("https://api.anthropic.com/v1/messages",
        headers={"x-api-key":KEY_ANT,"anthropic-version":"2023-06-01","content-type":"application/json"},
        json={"model":"claude-3-5-sonnet-20241022","max_tokens":1024,"system":sys,"messages":msgs},timeout=60)
    d=r.json()
    try: return d["content"][0]["text"],0
    except: return f"S塔錯誤: {d.get('error',{}).get('message','?')}", 0

def call_x(sys,hist,msg):
    msgs=[{"role":"system","content":sys}]+hist[-60:]+[{"role":"user","content":msg}]
    r=requests.post("https://api.openai.com/v1/chat/completions",
        headers={"Authorization":f"Bearer {KEY_OAI}","Content-Type":"application/json"},
        json={"model":"gpt-4o-mini","messages":msgs,"max_tokens":800},timeout=60)
    d=r.json()
    try: return d["choices"][0]["message"]["content"],0
    except: return f"X塔錯誤: {d.get('error',{}).get('message','?')}", 0

CALL_MAP={"F":call_f,"T":call_t,"S":call_s,"X":call_x}

def detect(txt):
    t=txt.lower()
    if any(k in t for k in ["code","程式","python","def ","邏輯","bug","寫個"]): return "F"
    if any(k in t for k in ["最新","今天","查","新聞","資料","介紹"]): return "T"
    if any(k in t for k in ["分析","哲學","架構","深入","北斗","道"]): return "S"
    if any(k in t for k in ["決策","風險","治理","建議","對策"]): return "X"
    return "F"

def send(cid, text, rid=None, kb=None):
    for i in range(0,len(text),4000):
        p={"chat_id":cid,"text":text[i:i+4000],"parse_mode":"Markdown"}
        if rid and i==0: p["reply_to_message_id"]=rid
        if kb and i+4000>=len(text): p["reply_markup"]=kb
        try: requests.post(f"{API}/sendMessage",json=p,timeout=10)
        except: pass

def handle(msg):
    cid=msg["chat"]["id"]; txt=msg.get("text","").strip(); mid=msg.get("message_id")
    if not txt: return
    key=str(cid)
    if txt=="/start":
        kb={"inline_keyboard":[[{"text":"⚙️F邏輯","callback_data":"mode_F"},{"text":"🌐T事實","callback_data":"mode_T"}],[{"text":"🔮S秩序","callback_data":"mode_S"},{"text":"⚖️X治理","callback_data":"mode_X"}],[{"text":"🤖自動","callback_data":"mode_CHAT"},{"text":"🗑清除","callback_data":"clear"}]]}
        send(cid,"*XTFS Bot v5.2 PA版* 🚀\n\n⚙️ F·Groq — 邏輯/程式\n🌐 T·Gemini — 事實/廣度\n🔮 S·Claude — 秩序/架構\n⚖️ X·ChatGPT — 治理/決策\n\n無 timeout 限制！",kb=kb); return
    if txt=="/clear": memory[key]=[]; send(cid,"✅ 記憶清除"); return
    forced=None
    for cmd,tower in [("/logic ","F"),("/fact ","T"),("/claude ","S"),("/s ","S"),("/govern ","X"),("/x ","X"),("/f ","F"),("/t ","T")]:
        if txt.startswith(cmd): forced,txt=tower,txt[len(cmd):].strip(); break
    if not txt: return
    tid=forced if forced else detect(txt)
    tower=TOWERS.get(tid,TOWERS["F"]); call_fn=CALL_MAP.get(tid,call_f)
    hist=memory.get(key,[])
    st=time.time()
    try: out,tk=call_fn(tower["p"],hist,txt)
    except Exception as e: out,tk=f"❌ {e}",0
    el=time.time()-st
    hist.append({"role":"user","content":txt}); hist.append({"role":"assistant","content":out})
    memory[key]=hist[-200:]
    fb={"inline_keyboard":[[{"text":"👍","callback_data":"good"},{"text":"👎","callback_data":"bad"},{"text":"🗑","callback_data":"clear"}]]}
    send(cid,f"{tower['e']} *{tower['n']}*\n\n{out}\n\n---\n{el:.1f}s | {tk}tk",rid=mid,kb=fb)

def handle_cb(q):
    cid=q["message"]["chat"]["id"]; d=q.get("data",""); qid=q.get("id")
    try: requests.post(f"{API}/answerCallbackQuery",json={"callback_query_id":qid},timeout=5)
    except: pass
    if d=="clear": memory[str(cid)]=[]; send(cid,"✅ 清除完成")
    elif d.startswith("mode_"):
        tid=d[5:]; t=TOWERS.get(tid,TOWERS["F"])
        send(cid,f"{t['e']} *{t['n']}* 就緒！直接發問。")

def run():
    offset=0
    print("✅ XTFS Bot v5.2 PA版 啟動")
    while True:
        try:
            r=requests.get(f"{API}/getUpdates",params={"offset":offset,"timeout":30},timeout=35)
            for u in r.json().get("result",[]):
                offset=u["update_id"]+1
                if "message" in u: threading.Thread(target=handle,args=(u["message"],),daemon=True).start()
                elif "callback_query" in u: handle_cb(u["callback_query"])
        except: time.sleep(3)

if __name__=="__main__":
    run()
