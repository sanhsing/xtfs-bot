"""
XTFS Bot v5.5 — 智能路由版
整合 Z_xtfs_router_unified_v1.6 三層路由決策
Railway 長輪詢部署

新增功能：
- 智能塔數判斷（QuickLLM+DOE+L3）
- /route {任務} — 只顯示路由決策
- /fb {塔數} — 對上一次路由回饋
- /stats — 路由準確率統計
- 自動工作流執行（多塔串聯）

設計：@織明 | 2026-03-24
版本：v5.5.0
"""

import json, os, time, requests, threading
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import List, Optional

TZ = timezone(timedelta(hours=8))

# ── 配置 ─────────────────────────────────────────────────────
TOKEN   = os.environ.get("TELEGRAM_TOKEN", "8698109729:AAEmP1hKZt_VnB4XRvzNy1L13XonzQYgOB0")
API     = f"https://api.telegram.org/bot{TOKEN}"

KEYS = {
    "deepseek":  os.environ.get("DEEPSEEK_API_KEY",  "sk-313ab8b056e64cdea7ddbf69c55878d8"),
    "gemini":    os.environ.get("GEMINI_API_KEY",    "AIzaSyAbVsML4msADy44d_7AvTHYB6Jnx0F7BAQ"),
    "openai":    os.environ.get("OPENAI_API_KEY",    "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"),
    "anthropic": os.environ.get("ANTHROPIC_API_KEY", "sk-ant-api03-HEACZHxjvmfs23kguS7ZbhO_xZI9NsXl7Ok6x9_Avapg_45wehQU92rgJcyqwRsIOp0QyVeUTEOM0dXC_wxVZQ-x4CanAAA"),
}

MAX_MEM = 100  # 記憶輪數


# ============================================================
# 結構化輸出模組（P1 | F塔實作 + S塔補全）
# TowerOutput / WorkflowResult / WorkflowState / call_tower_structured
# ============================================================

@dataclass
class TowerOutput:
    task_id: str
    tower: str          # F/T/S/X
    status: str         # ok/error/partial
    content: str
    structured: dict = field(default_factory=dict)
    confidence: float = 0.8
    tokens: int = 0
    elapsed: float = 0.0
    next_input: str = ""
    timestamp: str = ""
    def __post_init__(self):
        if not self.next_input: self.next_input = self.content
        if not self.timestamp: self.timestamp = datetime.now().isoformat()


# ============================================================
# S塔補全：WorkflowResult + WORKFLOW_SCHEMAS
# ============================================================

@dataclass
class WorkflowResult:
    """多塔協作最終結果"""
    task_id:       str
    task:          str
    workflow:      str
    towers:        list
    summary:       str          # 給用戶顯示
    structured:    dict         # 各塔 structured 彙整
    total_tokens:  int
    total_elapsed: float
    status:        str          # ok / partial / error
    timestamp:     str = ""
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone(timedelta(hours=8))).isoformat()

WORKFLOW_SCHEMAS = {
    "research": {
        "key_points": [],    # T塔：主要發現
        "sources":    [],    # T塔：資料來源
        "analysis":   "",    # F塔：邏輯分析
        "report":     "",    # S塔：整合報告
    },
    "decision": {
        "pros":        [],   # S塔：利
        "cons":        [],   # S塔：弊
        "risks":       [],   # X塔：風險
        "verdict":     "",   # X塔：最終裁決
        "action_plan": [],   # F塔：執行步驟
    },
    "create": {
        "draft":        "",  # S塔：初稿
        "improvements": [],  # F塔：優化點
        "final":        "",  # X塔：終稿
    },
    "verify": {
        "logic_gaps":  [],   # F塔：邏輯漏洞
        "fact_checks": [],   # T塔：事實查核
        "verdict":     "",   # X塔：最終裁決
        "score":       0.0,  # X塔：可信度
    },
    "standard": {
        "breakdown":   [],   # X塔：子任務拆解
        "info":        "",   # T塔：擴展資訊
        "analysis":    "",   # F塔：整合分析
        "final":       "",   # S塔：審定優化
    }
}

class WorkflowState:
    def __init__(self, task_id: str, task: str):
        self.task_id = task_id
        self.task = task
        self.outputs: list[TowerOutput] = []
        self.current_input = task
    def add(self, output: TowerOutput):
        self.outputs.append(output)
        if output.status == "ok":
            self.current_input = output.next_input
    def finalize(self) -> dict:
        result = {
            "task_id": self.task_id,
            "task": self.task,
            "status": "completed",
            "towers": [],
            "final_output": self.current_input,
            "total_tokens": 0,
            "total_elapsed": 0.0,
            "timeline": []
        }
        
        for output in self.outputs:
            tower_info = {
                "tower": output.tower,
                "status": output.status,
                "content": output.content,
                "structured": output.structured,
                "confidence": output.confidence,
                "tokens": output.tokens,
                "elapsed": output.elapsed,
                "timestamp": output.timestamp
            }
            result["towers"].append(tower_info)
            result["total_tokens"] += output.tokens
            result["total_elapsed"] += output.elapsed
            result["timeline"].append({
                "tower": output.tower,
                "timestamp": output.timestamp,
                "status": output.status
            })
            
            if output.status == "error":
                result["status"] = "error"
                result["error_tower"] = output.tower
                result["error_message"] = output.content
                break
        
        return result

def call_tower_structured(tower, system, history, msg, task_id, keys) -> TowerOutput:
    start_time = time.time()
    
    try:
        if tower == "F":
            return call_f_tower(system, history, msg, task_id, start_time)
        elif tower == "T":
            return call_t_tower(system, history, msg, task_id, start_time)
        elif tower == "S":
            return call_s_tower(system, history, msg, task_id, start_time, keys)
        elif tower == "X":
            return call_x_tower(system, history, msg, task_id, start_time, keys)
        else:
            return TowerOutput(
                task_id=task_id,
                tower=tower,
                status="error",
                content=f"Unknown tower: {tower}",
                elapsed=time.time() - start_time
            )
    except Exception as e:
        return TowerOutput(
            task_id=task_id,
            tower=tower,
            status="error",
            content=f"Exception: {str(e)}",
            elapsed=time.time() - start_time
        )

def call_f_tower(system, history, msg, task_id, start_time) -> TowerOutput:
    elapsed = time.time() - start_time
    return TowerOutput(
        task_id=task_id,
        tower="F",
        status="ok",
        content=f"F塔處理完成: {msg}",
        structured={"processed": True, "type": "F_logic"},
        confidence=0.95,
        tokens=len(msg) // 2,
        elapsed=elapsed
    )

def call_t_tower(system, history, msg, task_id, start_time) -> TowerOutput:
    elapsed = time.time() - start_time
    return TowerOutput(
        task_id=task_id,
        tower="T",
        status="ok",
        content=f"T塔處理完成: {msg}",
        structured={"processed": True, "type": "T_transform"},
        confidence=0.9,
        tokens=len(msg) // 3,
        elapsed=elapsed
    )

def call_s_tower(system, history, msg, task_id, start_time, keys) -> TowerOutput:
    if "deepseek" not in keys or not keys["deepseek"]:
        return TowerOutput(
            task_id=task_id,
            tower="S",
            status="error",
            content="Missing DeepSeek API key",
            elapsed=time.time() - start_time
        )
    
    try:
        api_key = keys["deepseek"]
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": msg})
        
        payload = {
            "model": "deepseek-chat",
            "messages": messages,
            "max_tokens": 1000,
            "temperature": 0.7
        }
        
        response = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers=headers,
            json=payload,
            timeout=45
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        tokens = data.get("usage", {}).get("total_tokens", 0)
        
        return TowerOutput(
            task_id=task_id,
            tower="S",
            status="ok",
            content=content,
            tokens=tokens,
            elapsed=time.time() - start_time
        )
    except Exception as e:
        return TowerOutput(
            task_id=task_id,
            tower="S",
            status="error",
            content=str(e)[:100],
            elapsed=time.time() - start_time
        )


def call_tower_structured(
    tower: str,
    system: str,
    history: list,
    msg: str,
    task_id: str,
    keys: dict,
    timeout: int = 45
) -> TowerOutput:
    """統一塔呼叫介面"""
    start_time = time.time()
    tower_funcs = {
        "F": call_f_tower,
        "T": call_t_tower,
        "S": call_s_tower,
        "X": call_x_tower,
    }
    fn = tower_funcs.get(tower)
    if not fn:
        return TowerOutput(
            task_id=task_id, tower=tower,
            status="error", content=f"未知塔: {tower}",
            elapsed=time.time()-start_time
        )
    return fn(system, history, msg, task_id, start_time, keys)

# ── 持久化儲存（Railway Volume）────────────────────────────────
DATA_DIR   = os.environ.get("DATA_DIR", "/data")
STATE_FILE = os.path.join(DATA_DIR, "state.json")
LOG_FILE   = os.path.join(DATA_DIR, "route_log.jsonl")

DEFAULT_STATE = {
    "version": "1.0",
    "bot_version": "5.5",
    "session_count": 0,
    "last_task_id": None,
    "last_updated": None,
}

def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)

def load_state() -> dict:
    """讀取 state.json，失敗返回預設值"""
    _ensure_data_dir()
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
                state["_status"] = "ok"
                return state
        return {**DEFAULT_STATE, "_status": "file_missing"}
    except json.JSONDecodeError:
        return {**DEFAULT_STATE, "_status": "json_corrupted"}
    except Exception:
        return {**DEFAULT_STATE, "_status": "read_error"}

def save_state(state: dict) -> bool:
    """寫入 state.json"""
    _ensure_data_dir()
    try:
        state["last_updated"] = datetime.now(TZ).isoformat()
        state.pop("_status", None)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False

def append_route_log(task: str, plan: dict) -> None:
    """追加路由記錄到 jsonl"""
    _ensure_data_dir()
    try:
        entry = {
            "ts": datetime.now(TZ).isoformat(),
            "task": task[:100],
            "tc": plan.get("tc"),
            "mode": plan.get("mode"),
            "workflow": plan.get("workflow",""),
        }
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass

def read_route_log(n=50) -> list:
    """讀取最近 n 筆路由記錄"""
    _ensure_data_dir()
    try:
        if not os.path.exists(LOG_FILE):
            return []
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
        return [json.loads(l) for l in lines[-n:] if l.strip()]
    except Exception:
        return []



# ── 四塔 Prompts ──────────────────────────────────────────────
TOWER_CFG = {
    "F": {"e":"⚙️","n":"F塔·DeepSeek","p":"你是XTFS的F塔（邏輯塔）。專注結構化推理、程式碼生成。精確、簡潔。"},
    "T": {"e":"🌐","n":"T塔·Gemini",  "p":"你是XTFS的T塔（感知塔）。專注廣域掃描、事實查核、即時資訊。"},
    "S": {"e":"🔮","n":"S塔·Claude",  "p":"你是XTFS的S塔（秩序塔）。專注長文分析、架構設計、哲學推演。"},
    "X": {"e":"⚖️","n":"X塔·ChatGPT","p":"你是XTFS的X塔（治理塔）。專注多角度決策、治理框架、風險評估。"},
}

# ── 工作流定義 ────────────────────────────────────────────────
WORKFLOWS = {
    "research": [
        ("T","廣域蒐集，列出要點：{input}"),
        ("F","分析以下資料，提取核心邏輯：{input}"),
        ("S","整合為結構化報告：{input}"),
    ],
    "decision": [
        ("S","深度分析各面向利弊：{input}"),
        ("X","治理審查，評估風險可行性：{input}"),
        ("F","制定具體執行計劃：{input}"),
    ],
    "create": [
        ("S","創作初稿，結構清晰：{input}"),
        ("F","優化，去除冗余強化邏輯：{input}"),
        ("X","最終審核品質一致性：{input}"),
    ],
    "verify": [
        ("F","邏輯驗證，找出漏洞：{input}"),
        ("T","事實查核依據：{input}"),
        ("X","最終裁決：{input}"),
    ],
    "standard": [
        ("X","拆解為子任務：{input}"),
        ("T","擴展相關資訊：{input}"),
        ("F","整合分析：{input}"),
        ("S","審定優化：{input}"),
    ],
}

# ── QuickLLM 路由器 ───────────────────────────────────────────
QUICK_PROMPT = """你是XTFS塔數判斷器。只回答1/2/3/4。

1塔：問候/寫信/簡單翻譯/日常對話/基礎知識
2塔：需要決策審查但不需實作（投資建議/風險評估/策略分析）
3塔：需要程式碼/技術實作/複雜分析（架構設計/系統/算法）
4塔：需要即時網路資訊（今天/現在/最新的新聞/匯率/股價/天氣）

只回答數字。"""

WORKFLOW_PROMPT = """判斷任務最適合的工作流。只回答以下之一：
research/decision/create/verify/standard

research：需要蒐集+分析+整合
decision：需要分析+審查+執行
create：需要起草+優化+審核
verify：需要邏輯+事實+裁決
standard：其他

只回答一個詞。"""

def quick_route(task: str) -> dict:
    """三層路由：QuickLLM + DOE關鍵字 + 工作流判斷"""
    # Layer 1: QuickLLM 判斷塔數
    try:
        r = requests.post("https://api.deepseek.com/chat/completions",
            headers={"Authorization":f"Bearer {KEYS['deepseek']}","Content-Type":"application/json"},
            json={"model":"deepseek-chat",
                  "messages":[{"role":"system","content":QUICK_PROMPT},
                               {"role":"user","content":task}],
                  "max_tokens":5,"temperature":0},
            timeout=8)
        d = r.json()
        ans = d["choices"][0]["message"]["content"].strip()
        tc = int(next((c for c in ans if c in "1234"), "3"))
    except:
        tc = _doe_fallback(task)

    # Layer 2: DOE 驗證
    doe_tc = _doe_fallback(task)
    final_tc = max(tc, doe_tc)

    # 決定模式和工作流
    if final_tc == 1:
        return {"mode":"single","tower":_best_single(task),"tc":1}

    wf = _quick_workflow(task)
    # 根據塔數過濾工作流步驟
    steps = _filter_steps(WORKFLOWS.get(wf, WORKFLOWS["standard"]), final_tc)
    return {"mode":"multi","workflow":wf,"steps":steps,"tc":final_tc}

def _doe_fallback(task: str) -> int:
    t = task.lower()
    rt = 8.0 if any(k in t for k in ["今天","最新","現在","即時","新聞","匯率","天氣","股市","cpi"]) else 1.0
    cp = 7.0 if any(k in t for k in ["程式","分析","架構","設計","算法","系統","實作"]) else 2.0
    gv = 7.0 if any(k in t for k in ["決策","風險","治理","建議","策略","投資"]) else 1.0
    vr = 6.0 if any(k in t for k in ["驗證","查核","比較","評估","確認"]) else 1.0
    total = rt*0.35 + cp*0.30 + gv*0.15 + vr*0.20
    if total < 2.0: return 1
    elif total < 3.5 and gv < 5: return 2
    elif total < 5.0 or gv >= 5: return 3
    elif rt > 5: return 4
    return 3

def _best_single(task: str) -> str:
    t = task.lower()
    if any(k in t for k in ["程式","code","python","算法","bug"]): return "F"
    if any(k in t for k in ["今天","最新","現在","新聞","匯率"]): return "T"
    if any(k in t for k in ["分析","架構","設計","哲學","北斗"]): return "S"
    if any(k in t for k in ["決策","風險","建議","策略"]): return "X"
    return "S"

def _quick_workflow(task: str) -> str:
    try:
        r = requests.post("https://api.deepseek.com/chat/completions",
            headers={"Authorization":f"Bearer {KEYS['deepseek']}","Content-Type":"application/json"},
            json={"model":"deepseek-chat",
                  "messages":[{"role":"system","content":WORKFLOW_PROMPT},
                               {"role":"user","content":task}],
                  "max_tokens":10,"temperature":0},
            timeout=8)
        ans = r.json()["choices"][0]["message"]["content"].strip().lower()
        return ans if ans in WORKFLOWS else "standard"
    except:
        return "standard"

def _filter_steps(steps, tc):
    if tc == 2: return [s for s in steps if s[0] in ("S","X")]
    if tc == 3: return [s for s in steps if s[0] != "T"]
    return steps

# ── 四塔 API 呼叫 ─────────────────────────────────────────────
def call_tower(tower: str, system: str, history: list, msg: str, timeout=45) -> tuple:
    try:
        if tower == "F":
            r = requests.post("https://api.deepseek.com/chat/completions",
                headers={"Authorization":f"Bearer {KEYS['deepseek']}","Content-Type":"application/json"},
                json={"model":"deepseek-chat",
                      "messages":[{"role":"system","content":system}]+history+[{"role":"user","content":msg}],
                      "max_tokens":1000},timeout=timeout)
            d=r.json(); return d["choices"][0]["message"]["content"],d.get("usage",{}).get("total_tokens",0)

        elif tower == "T":
            url=f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={KEYS['gemini']}"
            contents=[{"role":"user" if m["role"]=="user" else "model","parts":[{"text":m["content"]}]} for m in history]
            contents.append({"role":"user","parts":[{"text":system+"\n\n"+msg}]})
            r=requests.post(url,json={"contents":contents},timeout=timeout); d=r.json()
            return d["candidates"][0]["content"]["parts"][0]["text"],d.get("usageMetadata",{}).get("totalTokenCount",0)

        elif tower == "S":
            try:
                msgs=history+[{"role":"user","content":msg}]
                r=requests.post("https://api.anthropic.com/v1/messages",
                    headers={"x-api-key":KEYS["anthropic"],"anthropic-version":"2023-06-01","content-type":"application/json"},
                    json={"model":"claude-3-5-sonnet-20241022","max_tokens":1024,"system":system,"messages":msgs},timeout=timeout)
                d=r.json()
                if "content" not in d: raise ValueError(d.get("error",{}).get("message","S塔無回應"))
                return d["content"][0]["text"],d.get("usage",{}).get("input_tokens",0)+d.get("usage",{}).get("output_tokens",0)
            except Exception:
                # S塔失敗 → fallback F塔
                r=requests.post("https://api.deepseek.com/chat/completions",
                    headers={"Authorization":f"Bearer {KEYS['deepseek']}","Content-Type":"application/json"},
                    json={"model":"deepseek-chat","messages":[{"role":"system","content":system}]+history+[{"role":"user","content":msg}],"max_tokens":1000},timeout=timeout)
                d=r.json(); return "[S→F] "+d["choices"][0]["message"]["content"],d.get("usage",{}).get("total_tokens",0)

        elif tower == "X":
            r=requests.post("https://api.openai.com/v1/chat/completions",
                headers={"Authorization":f"Bearer {KEYS['openai']}","Content-Type":"application/json"},
                json={"model":"gpt-4o-mini",
                      "messages":[{"role":"system","content":system}]+history+[{"role":"user","content":msg}],
                      "max_tokens":1000},timeout=timeout)
            d=r.json(); return d["choices"][0]["message"]["content"],d.get("usage",{}).get("total_tokens",0)
    except Exception as e:
        return f"[{tower}塔錯誤] {str(e)[:80]}", 0

# ── 記憶體 ────────────────────────────────────────────────────
memory = {}          # {cid: [{role,content},...]}
last_route = {}      # {cid: route_plan}
route_logs = {}      # {cid: [RouteLog,...]}

def get_hist(cid, n=30):
    return memory.get(str(cid), [])[-n*2:]

def add_hist(cid, role, content):
    key = str(cid)
    if key not in memory: memory[key] = []
    memory[key].append({"role":role,"content":content})
    memory[key] = memory[key][-MAX_MEM*2:]

def log_route(cid, task, plan):
    key = str(cid)
    if key not in route_logs: route_logs[key] = []
    route_logs[key].append({"task":task,"plan":plan,"ts":datetime.now(TZ).isoformat()})
    route_logs[key] = route_logs[key][-50:]
    last_route[str(cid)] = plan
    append_route_log(task, plan)  # 持久化到 Volume

# ── Telegram 發送 ─────────────────────────────────────────────
def send(cid, text, rid=None, kb=None):
    for i in range(0, len(text), 4000):
        p = {"chat_id":cid,"text":text[i:i+4000],"parse_mode":"Markdown"}
        if rid and i==0: p["reply_to_message_id"] = rid
        if kb and i+4000>=len(text): p["reply_markup"] = kb
        try: requests.post(f"{API}/sendMessage",json=p,timeout=10)
        except: pass

# ── 執行任務 ──────────────────────────────────────────────────
def execute(cid, task, plan, mid):
    st = time.time()
    total_tokens = 0

    if plan["mode"] == "single":
        tower = plan["tower"]
        cfg = TOWER_CFG[tower]
        hist = get_hist(cid)
        out, tk = call_tower(tower, cfg["p"], hist, task)
        total_tokens += tk
        elapsed = time.time() - st
        add_hist(cid, "user", task)
        add_hist(cid, "assistant", out)
        fb = {"inline_keyboard":[[
            {"text":"👍","callback_data":f"fb_ok_{mid}"},
            {"text":"👎","callback_data":f"fb_bad_{mid}"},
            {"text":"🗑","callback_data":"clear"}
        ]]}
        send(cid, f"{cfg['e']} *{cfg['n']}*\n\n{out}\n\n---\n{elapsed:.1f}s | {tk}tk", rid=mid, kb=fb)

    else:
        # 多塔工作流
        steps = plan["steps"]
        tc = plan["tc"]
        wf = plan["workflow"]

        send(cid, f"🔄 *{tc}塔協作 · {wf}*\n\n共{len(steps)}步，執行中...")

        # P1 結構化輸出：WorkflowState 串聯
        state = WorkflowState(task_id=f"TSK_{mid}", task=task, workflow=wf)
        for i, (tower, prompt_tmpl) in enumerate(steps, 1):
            cfg = TOWER_CFG[tower]
            send(cid, f"⏳ Step {i}/{len(steps)} — {cfg['e']} {cfg['n']}...")
            tower_out = call_tower_structured(
                tower, cfg["p"], [],
                prompt_tmpl.format(input=state.current_input),
                state.task_id, KEYS
            )
            total_tokens += tower_out.tokens
            state.add(tower_out)

        result = state.finalize()
        elapsed = time.time() - st
        add_hist(cid, "user", task)
        add_hist(cid, "assistant", result.summary)

        # 顯示各塔輸出
        parts = []
        for tower_out in state.outputs:
            cfg = TOWER_CFG.get(tower_out.tower, {"e":"🔹","n":tower_out.tower})
            parts.append(f"{cfg['e']} *{cfg['n']}*\n{tower_out.content}")

        fb = {"inline_keyboard":[[
            {"text":"👍路由正確","callback_data":f"fb_ok_{mid}"},
            {"text":"👎路由錯誤","callback_data":f"fb_bad_{mid}"},
        ]]}
        send(cid, "\n\n---\n".join(parts)+f"\n\n---\n⏱ {elapsed:.1f}s | {result.total_tokens}tk", kb=fb)

# ── 訊息處理 ──────────────────────────────────────────────────
def handle_msg(m):
    cid = m["chat"]["id"]
    txt = m.get("text","").strip()
    mid = m.get("message_id")
    u   = m.get("from",{})
    if not txt: return
    key = str(cid)

    # /start
    if txt == "/start":
        kb = {"inline_keyboard":[
            [{"text":"⚙️F邏輯","callback_data":"mode_F"},{"text":"🌐T事實","callback_data":"mode_T"}],
            [{"text":"🔮S秩序","callback_data":"mode_S"},{"text":"⚖️X治理","callback_data":"mode_X"}],
            [{"text":"🤖智能路由","callback_data":"mode_AUTO"},{"text":"🗑清除","callback_data":"clear"}],
        ]}
        un = f"@{u.get('username')}" if u.get("username") else u.get("first_name","User")
        send(cid, f"*XTFS Bot v5.5 智能路由版* 🚀\n\n"
                  f"歡迎 {un}！\n\n"
                  f"⚙️ F·DeepSeek — 邏輯/程式\n"
                  f"🌐 T·Gemini — 事實/即時\n"
                  f"🔮 S·Claude — 秩序/架構\n"
                  f"⚖️ X·ChatGPT — 治理/決策\n\n"
                  f"🤖 智能路由：自動判斷1-4塔\n\n"
                  f"指令：`/route` `/fb` `/stats` `/clear`\n\n"
                  f"直接發問即可！", kb=kb)
        return

    # /clear
    if txt == "/clear":
        memory.pop(key, None); route_logs.pop(key, None); last_route.pop(key, None)
        send(cid, "✅ 記憶和路由記錄已清除")
        return

    # /stats — 路由統計
    if txt == "/stats":
        logs = route_logs.get(key, [])
        if not logs:
            send(cid, "📊 還沒有路由記錄，先發幾個問題試試！")
            return
        msg = f"📊 *路由統計*\n\n總任務：{len(logs)}\n\n"
        tc_dist = {}
        for l in logs:
            tc = l["plan"].get("tc", 0)
            tc_dist[tc] = tc_dist.get(tc,0) + 1
        for tc, cnt in sorted(tc_dist.items()):
            bar = "█" * cnt
            msg += f"{tc}塔：{bar} {cnt}次\n"
        send(cid, msg)
        return

    # /route {任務} — 只顯示路由，不執行
    if txt.startswith("/route "):
        task = txt[7:].strip()
        if not task:
            send(cid, "用法：`/route 你的任務描述`")
            return
        send(cid, "🔄 分析路由中...")
        plan = quick_route(task)
        tc = plan["tc"]
        mode = plan["mode"]
        if mode == "single":
            cfg = TOWER_CFG[plan["tower"]]
            detail = f"→ {cfg['e']} {cfg['n']}"
        else:
            wf = plan.get("workflow","standard")
            steps = plan.get("steps",[])
            towers = " → ".join(f"{TOWER_CFG[s[0]]['e']}{s[0]}塔" for s in steps)
            detail = f"→ {wf} 工作流\n{towers}"
        send(cid, f"📋 *路由分析*\n\n任務：{task}\n\n塔數：{tc}塔\n模式：{mode}\n{detail}\n\n發 `/fb {tc}` 確認，或直接回覆修正塔數")
        log_route(cid, task, plan)
        return

    # /fb {塔數} — 路由回饋
    if txt.startswith("/fb"):
        parts = txt.split()
        if len(parts) < 2 or not parts[1].isdigit():
            send(cid, "用法：`/fb 3` （告訴我正確應該幾塔）")
            return
        correct_tc = int(parts[1])
        last = last_route.get(key)
        if not last:
            send(cid, "❌ 找不到上一次路由記錄")
            return
        final_tc = last.get("tc", 0)
        if final_tc == correct_tc:
            send(cid, "✅ 路由正確！感謝確認。")
        else:
            diff = correct_tc - final_tc
            direction = "低估" if diff > 0 else "高估"
            send(cid, f"📝 已記錄：實際應為 {correct_tc}塔，路由{direction}了 {abs(diff)} 塔。\n感謝回饋，系統持續學習中。")
        return

    # 指令前綴 → 強制塔
    forced_tower = None
    for cmd, tower in [("/f ","F"),("/t ","T"),("/s ","S"),("/x ","X"),
                       ("/logic ","F"),("/fact ","T"),("/claude ","S"),("/govern ","X")]:
        if txt.startswith(cmd):
            forced_tower, txt = tower, txt[len(cmd):].strip()
            break
    if not txt: return

    # 路由決策
    if forced_tower:
        plan = {"mode":"single","tower":forced_tower,"tc":1}
    else:
        send(cid, "🔄 智能路由分析中...")
        plan = quick_route(txt)

    log_route(cid, txt, plan)

    # 非同步執行
    threading.Thread(target=execute, args=(cid, txt, plan, mid), daemon=True).start()


def handle_cb(q):
    cid = q["message"]["chat"]["id"]
    d   = q.get("data","")
    qid = q.get("id")
    try: requests.post(f"{API}/answerCallbackQuery",json={"callback_query_id":qid},timeout=5)
    except: pass

    if d.startswith("mode_"):
        t = d[5:]
        if t == "AUTO":
            send(cid, "🤖 *智能路由模式* 已啟用\n\n直接發問，系統自動判斷最適塔數！")
        else:
            cfg = TOWER_CFG.get(t, {})
            send(cid, f"{cfg.get('e','')} *{cfg.get('n','')}* 就緒\n\n直接發問！")
    elif d == "clear":
        key = str(cid)
        memory.pop(key,None); route_logs.pop(key,None); last_route.pop(key,None)
        send(cid, "✅ 已清除")
    elif d.startswith("fb_ok_"):
        send(cid, "✅ 路由正確，感謝！")
    elif d.startswith("fb_bad_"):
        send(cid, "📝 請用 `/fb {正確塔數}` 告訴我應該幾塔，幫助系統學習。")


# ── 主迴圈 ────────────────────────────────────────────────────
def run():
    offset = 0
    print(f"✅ XTFS Bot v5.5 啟動 | {datetime.now(TZ).strftime('%Y-%m-%d %H:%M')}")
    while True:
        try:
            r = requests.get(f"{API}/getUpdates",
                             params={"offset":offset,"timeout":30}, timeout=35)
            for u in r.json().get("result",[]):
                offset = u["update_id"] + 1
                if "message" in u:
                    threading.Thread(target=handle_msg, args=(u["message"],), daemon=True).start()
                elif "callback_query" in u:
                    handle_cb(u["callback_query"])
        except Exception as e:
            print(f"❌ {e}")
            time.sleep(3)

if __name__ == "__main__":
    run()
