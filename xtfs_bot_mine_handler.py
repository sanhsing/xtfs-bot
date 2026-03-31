"""
XTFS Bot — /mine 指令處理器
加到 @xtfs_beidou_bot (Vercel) 的 bot 主程式

當你傳 /mine 給 Bot → Bot 呼叫 Claude API → 回傳挖掘結果

部署步驟：
  1. 在 xtfsbot.vercel.app 的主程式加入這段 handler
  2. 設定 Vercel Cron（選用）: 每週二自動觸發

Vercel cron.json：
  {"crons": [{"path": "/api/cron/mine", "schedule": "0 13 * * 2"}]}
"""

import os, json, requests
from datetime import datetime

CLAUDE_API_KEY = os.environ.get('ANTHROPIC_API_KEY')
TG_BOT_TOKEN   = os.environ.get('TG_BOT_TOKEN', '8698109729:AAEmP1hKZt_VnB4XRvzNy1L13XonzQYgOB0')
TG_CHAT_ID     = '5965951659'

MINE_SYSTEM = """你是 XTFS Mining Agent。
每次執行時：
1. 呼叫 restore() 恢復狀態
2. 用三個策略搜 GDrive
3. process_results() 過濾並入庫
4. full_backup() 備份
5. 回傳簡短報告

只輸出 JSON：
{
  "wave": <int>,
  "new_docs": <int>,
  "skipped": <int>,
  "total_processed": <int>,
  "top_boi": [{"name": ..., "boi": ...}],
  "pa_backup": true/false,
  "tg_backup": true/false
}
"""

def handle_mine_command(chat_id: str = TG_CHAT_ID) -> dict:
    """處理 /mine 指令，呼叫 Claude API 執行挖掘"""

    # 呼叫 Claude API
    resp = requests.post(
        'https://api.anthropic.com/v1/messages',
        headers={
            'x-api-key': CLAUDE_API_KEY,
            'anthropic-version': '2023-06-01',
            'content-type': 'application/json',
        },
        json={
            'model': 'claude-sonnet-4-20250514',
            'max_tokens': 1000,
            'system': MINE_SYSTEM,
            'messages': [{'role': 'user', 'content': '執行本週 GDrive mining wave'}],
        },
        timeout=60
    )

    result = resp.json()
    report_text = result['content'][0]['text']

    # 解析 JSON 結果
    try:
        report = json.loads(report_text)
        msg = (
            f"✅ Mining Wave {report['wave']} 完成\n"
            f"新增: {report['new_docs']}個 | 跳過: {report['skipped']}個\n"
            f"累計: {report['total_processed']}個\n"
            f"PA: {'✅' if report['pa_backup'] else '❌'} | "
            f"TG: {'✅' if report['tg_backup'] else '❌'}"
        )
        if report.get('top_boi'):
            top = report['top_boi'][0]
            msg += f"\n最高BOI: [{top['boi']}] {top['name']}"
    except:
        msg = f"Mining 完成\n{report_text[:200]}"

    # 傳回 Telegram
    requests.post(
        f'https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage',
        json={'chat_id': chat_id, 'text': msg}
    )
    return {'ok': True, 'message': msg}


# Vercel Cron endpoint
def cron_handler(request):
    """每週二 21:00 自動觸發"""
    return handle_mine_command()
