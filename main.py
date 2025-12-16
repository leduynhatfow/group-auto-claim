import asyncio
import json
import os
import re
import time
import random
import websockets
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any
from colorama import Fore, Style
from curl_cffi import requests

# Try uvloop for performance
try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except: pass

# GLOBALS
claimed_groups: List[int] = []
userid: int = None
username: str = ""
cookie: str = ""
xcsrf: str = ""
session: requests.Session = None
stats = {'total': 0, 'success': 0, 'fail': 0}
claim_mode: str = "parallel"
parallel_delays: List[float] = [0.14, 0.15, 0.16]

# Load config
with open("config.json", "r") as f:
    config = json.load(f)
    webhooks = config["webhooks"]
    token = config["token"]
    prefix = config.get("prefix", "--")
    
    # Claim strategy config
    claim_mode = config.get("claim_mode", "parallel")
    parallel_delays = config.get("parallel_delays", [0.14, 0.15, 0.16])

def timet():
    return Style.BRIGHT + Fore.BLACK + f"[{datetime.now().strftime('%I:%M:%S')}] "

def log(text): print(f"{timet()}{Style.BRIGHT}{Fore.LIGHTMAGENTA_EX}INFO {Fore.WHITE}{Fore.RESET}{Style.BRIGHT}{Fore.BLACK} >  {Fore.RESET}{Fore.WHITE}{text}")
def ok(text): print(f"{timet()}{Style.BRIGHT}{Fore.LIGHTGREEN_EX}SUCCESS {Fore.WHITE}{Fore.RESET}{Style.BRIGHT}{Fore.BLACK} >  {Fore.RESET}{Fore.WHITE}{text}")
def warn(text): print(f"{timet()}{Style.BRIGHT}{Fore.LIGHTYELLOW_EX}WARN {Fore.WHITE}{Fore.RESET}{Style.BRIGHT}{Fore.BLACK} >  {Fore.RESET}{Fore.WHITE}{text}")
def fatal(text): print(f"{timet()}{Style.BRIGHT}{Fore.LIGHTRED_EX}ERROR {Fore.WHITE}{Fore.RESET}{Style.BRIGHT}{Fore.BLACK} >  {Fore.RESET}{Fore.WHITE}{text}")

# ==================== SESSION ====================
def init_session():
    global session
    session = requests.Session()
    session.impersonate = "chrome"
    log("⚡ Chrome session initialized")

# ==================== COOKIE MANAGER ====================
class CookieManager:
    def __init__(self):
        with open("cookies.txt", "r") as f:
            self.cookies = [c.strip() for c in f.readlines() if c.strip()]
        log(f"Loaded {len(self.cookies)} cookies")
    
    def get(self): 
        return random.choice(self.cookies) if self.cookies else None
    
    def remove(self, c):
        if c in self.cookies:
            self.cookies.remove(c)
            with open("cookies.txt", "w") as f:
                f.write("\n".join(self.cookies))
            log(f"Removed invalid cookie")

cookie_mgr = CookieManager()

# ==================== XCSRF & AUTH ====================
async def get_xcsrf(c):
    global session
    try:
        loop = asyncio.get_event_loop()
        r = await loop.run_in_executor(None, lambda: session.post(
            "https://auth.roblox.com/v2/logout",
            headers={"Cookie": f"GuestData=UserID=-174948669; .ROBLOSECURITY={c};"}
        ))
        return r.headers.get("x-csrf-token", "")
    except: return ""

async def get_user(c, x):
    global session
    try:
        loop = asyncio.get_event_loop()
        r = await loop.run_in_executor(None, lambda: session.get(
            "https://users.roblox.com/v1/users/authenticated",
            headers={"Cookie": f"GuestData=UserID=-174948669; .ROBLOSECURITY={c};", "X-CSRF-TOKEN": x}
        ))
        if r.status_code == 200:
            d = r.json()
            return {"id": d["id"], "name": d["name"]}
    except: pass
    return {}

async def switch_cookie():
    global cookie, xcsrf, userid, username, cookie_mgr
    c = cookie_mgr.get()
    if not c: 
        fatal("No cookies left!")
        return False
    x = await get_xcsrf(c)
    u = await get_user(c, x)
    if u:
        cookie, xcsrf, userid, username = c, x, u["id"], u["name"]
        ok(f"Switched to {username}")
        return True
    cookie_mgr.remove(c)
    return await switch_cookie()

async def xcsrf_refresher():
    """Auto refresh XCSRF every 10 minutes"""
    global xcsrf, cookie
    while True:
        await asyncio.sleep(600)
        if cookie:
            new_x = await get_xcsrf(cookie)
            if new_x:
                xcsrf = new_x
                log("XCSRF refreshed")

# ==================== ULTIMATE CLAIM ====================
async def ultimate_claim(gid: int) -> bool:
    """Claim with configurable strategy: Sequential or Parallel"""
    global cookie, xcsrf, session, claim_mode, parallel_delays
    
    headers = {
        "Content-Type": "application/json",
        "Cookie": f"GuestData=UserID=-174948669; .ROBLOSECURITY={cookie}; RBXEventTrackerV2=CreateDate=11/19/2023 12:07:42 PM&rbxid=5189165742&browserid=200781876902;",
        "X-CSRF-TOKEN": xcsrf,
    }
    
    if claim_mode == "sequential":
        return await claim_sequential(gid, headers)
    elif claim_mode == "parallel":
        return await claim_parallel(gid, headers)
    else:
        fatal(f"Invalid claim_mode: {claim_mode}")
        return False

# ==================== SEQUENTIAL STRATEGY ====================
async def claim_sequential(gid: int, headers: dict) -> bool:
    """Sequential: JOIN → wait → CLAIM"""
    global session
    try:
        log(f"🚀 Sequential: JOIN → wait → CLAIM")
        
        start_total = time.perf_counter()
        loop = asyncio.get_event_loop()
        
        # Fire JOIN
        start_join = time.perf_counter()
        jr = await loop.run_in_executor(None, lambda: session.post(
            f"https://groups.roblox.com/v1/groups/{gid}/users", headers=headers
        ))
        join_time = (time.perf_counter() - start_join) * 1000
        
        log(f"JOIN completed: {jr.status_code} ({join_time:.0f}ms)")
        
        start_claim = time.perf_counter()
        cr = await loop.run_in_executor(None, lambda: session.post(
            f"https://groups.roblox.com/v1/groups/{gid}/claim-ownership", headers=headers
        ))
        claim_time = (time.perf_counter() - start_claim) * 1000
        total_time = (time.perf_counter() - start_total) * 1000
        
        log(f"Sequential - JOIN: {jr.status_code} ({join_time:.0f}ms) | CLAIM: {cr.status_code} ({claim_time:.0f}ms) | Total: {total_time:.0f}ms")
        
        if cr.status_code == 200:
            ok(f"✅ CLAIMED {gid} | Sequential | JOIN: {join_time:.0f}ms | CLAIM: {claim_time:.0f}ms | Total: {total_time:.0f}ms")
            stats['success'] += 1
            
            asyncio.create_task(send_success_webhook(gid, total_time, join_time, claim_time, 0, 'Sequential'))
            asyncio.create_task(set_group_status(gid))
            asyncio.create_task(check_group_value(gid))
            return True
        
        # Handle errors
        return await handle_claim_errors(gid, jr, cr)
                
    except Exception as e:
        fatal(f"{gid} - Sequential error: {type(e).__name__}")
        stats['fail'] += 1
        return False

# ==================== PARALLEL STRATEGY ====================
async def claim_parallel(gid: int, headers: dict) -> bool:
    """1 JOIN + Multiple parallel CLAIMs with different delays"""
    global parallel_delays, session
    
    try:
        delays_str = " | ".join([f"{int(d*1000)}ms" for d in parallel_delays])
        log(f"🚀 Parallel: 1 JOIN + {len(parallel_delays)} CLAIMs ({delays_str})")
        
        start_total = time.perf_counter()
        loop = asyncio.get_event_loop()
        
        start_join = time.perf_counter()
        join_task = loop.run_in_executor(None, lambda: session.post(
            f"https://groups.roblox.com/v1/groups/{gid}/users", headers=headers
        ))
        
        # Parallel CLAIM with delay
        async def parallel_claim_with_delay(delay: float, batch_num: int):
            try:
                await asyncio.sleep(delay)
                start_claim = time.perf_counter()
                cr = await loop.run_in_executor(None, lambda: session.post(
                    f"https://groups.roblox.com/v1/groups/{gid}/claim-ownership", headers=headers
                ))
                claim_time = (time.perf_counter() - start_claim) * 1000
                return {'batch': batch_num, 'delay': delay, 'cr': cr, 'claim_time': claim_time}
            except Exception as e:
                return {'batch': batch_num, 'delay': delay, 'error': str(e)}
        
        claim_tasks = [parallel_claim_with_delay(delay, i+1) for i, delay in enumerate(parallel_delays)]
        claim_results = await asyncio.gather(*claim_tasks, return_exceptions=True)
        
        jr = await join_task
        join_time = (time.perf_counter() - start_join) * 1000
        total_time = (time.perf_counter() - start_total) * 1000
        
        success_result = None
        
        for result in claim_results:
            if isinstance(result, Exception) or 'error' in result:
                if not isinstance(result, Exception):
                    warn(f"Batch {result['batch']} (delay {int(result['delay']*1000)}ms) - Error: {result['error']}")
                continue
            
            batch = result['batch']
            delay = result['delay']
            cr = result['cr']
            claim_time = result['claim_time']
            
            log(f"Batch {batch} (delay {int(delay*1000)}ms) - JOIN: {jr.status_code} ({join_time:.0f}ms) | CLAIM: {cr.status_code} ({claim_time:.0f}ms) | Total: {total_time:.0f}ms")
            
            if cr.status_code == 200 and success_result is None:
                success_result = result
        
        if success_result:
            batch = success_result['batch']
            delay = success_result['delay']
            cr = success_result['cr']
            claim_time = success_result['claim_time']
            
            ok(f"✅ CLAIMED {gid} | Parallel Batch {batch} (delay {int(delay*1000)}ms) | JOIN: {join_time:.0f}ms | CLAIM: {claim_time:.0f}ms | Total: {total_time:.0f}ms")
            stats['success'] += 1
            
            asyncio.create_task(send_success_webhook(gid, total_time, join_time, claim_time, delay, batch))
            asyncio.create_task(set_group_status(gid))
            asyncio.create_task(check_group_value(gid))
            return True
        
        if claim_results:
            first_result = next((r for r in claim_results if not isinstance(r, Exception) and 'error' not in r), None)
            if first_result:
                return await handle_claim_errors(gid, jr, first_result['cr'])
        
        stats['fail'] += 1
        return False
                
    except Exception as e:
        fatal(f"{gid} - Parallel error: {type(e).__name__}")
        stats['fail'] += 1
        return False

# ==================== ERROR HANDLER ====================
async def handle_claim_errors(gid: int, jr, cr) -> bool:
    """Handle claim errors"""
    global cookie, xcsrf, cookie_mgr
    
    # Handle CLAIM errors
    if cr.status_code == 403:
        if "Token" in cr.text:
            warn(f"{gid} - Invalid XCSRF (auto-fixing)")
            new_x = await get_xcsrf(cookie)
            if new_x:
                xcsrf = new_x
        else:
            warn(f"{gid} - Already claimed")
            asyncio.create_task(leave_group(gid))
            
    elif cr.status_code == 500:
        warn(f"{gid} - Already claimed (500)")
        asyncio.create_task(leave_group(gid))
        
    elif cr.status_code == 429:
        warn(f"{gid} - Rate limited, switching cookie")
        asyncio.create_task(switch_cookie())
    
    # Handle JOIN errors
    if jr.status_code == 403:
        try:
            msg = jr.json().get("errors", [{}])[0].get("message", "").lower()
            if "maximum" in msg:
                fatal("Account full! Switching...")
                cookie_mgr.remove(cookie)
                asyncio.create_task(switch_cookie())
            elif "challenge" in msg:
                warn("Challenge required, switching...")
                asyncio.create_task(switch_cookie())
        except: pass
            
    elif jr.status_code == 429:
        warn("Rate limited, switching cookie")
        asyncio.create_task(switch_cookie())
    
    stats['fail'] += 1
    return False

async def send_success_webhook(gid: int, total_ms: float, join_ms: float, claim_ms: float, delay: float, method):
    """Send success webhook"""
    global username, session
    try:
        if method == 'Sequential':
            fields = [
                {"name": "⚡ Total", "value": f"{total_ms:.0f}ms", "inline": True},
                {"name": "📥 JOIN", "value": f"{join_ms:.0f}ms", "inline": True},
                {"name": "🎯 CLAIM", "value": f"{claim_ms:.0f}ms", "inline": True},
                {"name": "🔧 Method", "value": "Sequential", "inline": True},
                {"name": "👤 User", "value": username, "inline": True}
            ]
        else:
            # Parallel batch
            fields = [
                {"name": "⚡ Total", "value": f"{total_ms:.0f}ms", "inline": True},
                {"name": "📥 JOIN", "value": f"{join_ms:.0f}ms", "inline": True},
                {"name": "🎯 CLAIM", "value": f"{claim_ms:.0f}ms", "inline": True},
                {"name": "⏱️ Delay", "value": f"{int(delay*1000)}ms", "inline": True},
                {"name": "🔢 Batch", "value": f"#{method}", "inline": True},
                {"name": "👤 User", "value": username, "inline": True}
            ]
        
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: session.post(
            webhooks["detections"],
            json={
                "username": " Ultra Fusion",
                "embeds": [{
                    "title": f"✅ {gid}",
                    "url": f"https://roblox.com/groups/{gid}",
                    "fields": fields,
                    "color": 0x00FF00,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }]
            }
        ))
    except: pass

async def set_group_status(gid: int):
    """Set group status"""
    global cookie, xcsrf, session
    try:
        messages = ["Catch me if you can!", " Ultra Fusion"]
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: session.patch(
            f"https://groups.roblox.com/v1/groups/{gid}/status",
            headers={
                "Cookie": f"GuestData=UserID=-174948669; .ROBLOSECURITY={cookie}; RBXEventTrackerV2=CreateDate=11/19/2023 12:07:42 PM&rbxid=5189165742&browserid=200781876902;",
                "X-CSRF-TOKEN": xcsrf,
            },
            json={"message": random.choice(messages)}
        ))
    except: pass

async def leave_group(gid: int):
    """Leave group"""
    global cookie, xcsrf, userid, session
    try:
        headers = {
            "Cookie": f"GuestData=UserID=-174948669; .ROBLOSECURITY={cookie}; RBXEventTrackerV2=CreateDate=11/19/2023 12:07:42 PM&rbxid=5189165742&browserid=200781876902;",
            "X-CSRF-TOKEN": xcsrf,
        }
        loop = asyncio.get_event_loop()
        r = await loop.run_in_executor(None, lambda: session.delete(
            f"https://groups.roblox.com/v1/groups/{gid}/users/{userid}",
            headers=headers
        ))
        if r.status_code == 200:
            log(f"Left group {gid}")
    except: pass

async def check_group_value(gid: int):
    """Check group value and send detailed webhook"""
    global cookie, xcsrf, session
    try:
        headers = {
            "Cookie": f"GuestData=UserID=-174948669; .ROBLOSECURITY={cookie}; RBXEventTrackerV2=CreateDate=11/19/2023 12:07:42 PM&rbxid=5189165742&browserid=200781876902;",
            "X-CSRF-TOKEN": xcsrf,
        }
        
        loop = asyncio.get_event_loop()
        today = datetime.now().strftime("%Y-%m-%d")
        
        # Fetch all data
        games_r, funds_r, pending_r, clothes_r, thumb_r = await asyncio.gather(
            loop.run_in_executor(None, lambda: session.get(
                f"https://games.roblox.com/v2/groups/{gid}/gamesV2?accessFilter=2&limit=100&sortOrder=Asc"
            )),
            loop.run_in_executor(None, lambda: session.get(
                f"https://economy.roblox.com/v1/groups/{gid}/currency", headers=headers
            )),
            loop.run_in_executor(None, lambda: session.get(
                f"https://economy.roblox.com/v1/groups/{gid}/revenue/summary/{today}", headers=headers
            )),
            loop.run_in_executor(None, lambda: session.get(
                f"https://catalog.roblox.com/v1/search/items/details?Category=3&SortType=Relevance&CreatorTargetId={gid}&ResultsPerPage=100&CreatorType=2"
            )),
            loop.run_in_executor(None, lambda: session.get(
                f"https://thumbnails.roblox.com/v1/groups/icons?groupIds={gid}&size=150x150&format=Png&isCircular=false"
            )),
            return_exceptions=True
        )
        
        # Parse data
        robux, revenue, games, visits, clothing, thumbnail = 0, 0, 0, 0, 0, None
        
        if not isinstance(funds_r, Exception) and funds_r.status_code == 200:
            robux = funds_r.json().get("robux", 0)
            
        if not isinstance(pending_r, Exception) and pending_r.status_code == 200:
            revenue = pending_r.json().get("pendingRobux", 0)
            
        if not isinstance(games_r, Exception) and games_r.status_code == 200:
            games_data = games_r.json().get("data", [])
            games = len(games_data)
            visits = sum(g.get("placeVisits", 0) for g in games_data)
            
        if not isinstance(clothes_r, Exception) and clothes_r.status_code == 200:
            clothing = len(clothes_r.json().get("data", []))
            
        if not isinstance(thumb_r, Exception) and thumb_r.status_code == 200:
            thumbnail = thumb_r.json()["data"][0]["imageUrl"]
        
        # Send detailed webhook if valuable
        if any([robux >= 100, revenue >= 100, games >= 5, visits >= 100, clothing >= 10]):
            embed = {
                "username": " - High Value Detection",
                "embeds": [{
                    "title": f"💎 High Value Group | {gid}",
                    "url": f"https://roblox.com/groups/{gid}",
                    "fields": [
                        {"name": "Robux", "value": f"{robux}", "inline": True},
                        {"name": "Pending", "value": f"{revenue}", "inline": True},
                        {"name": "Games", "value": f"{games}", "inline": True},
                        {"name": "Visits", "value": f"{visits}", "inline": True},
                        {"name": "Clothing", "value": f"{clothing}", "inline": True},
                    ],
                    "thumbnail": {"url": thumbnail} if thumbnail else {},
                    "color": 0xFFD700,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }]
            }
            
            await loop.run_in_executor(None, lambda: session.post(
                webhooks["detections"], json=embed
            ))
            ok(f"💎 High value group detected!")
            
    except Exception as e:
        pass

# ==================== CLAIM HANDLER ====================
async def handle_claim(gid: int):
    """Main claim handler"""
    if gid in claimed_groups:
        return
    
    claimed_groups.append(gid)
    stats['total'] += 1
    
    ok(f"🎯 Detected group: {gid}")
    await ultimate_claim(gid)

# ==================== DISCORD ====================
class Discord:
    def __init__(self, t):
        self.token = t
        self.ws = None
        self.hb_task = None
        self.seq = None
        self.sid = None
        self.url = None
        self.connected = False

    async def connect(self):
        while True:
            try:
                uri = self.url or "wss://gateway.discord.gg/?v=10&encoding=json"
                async with websockets.connect(uri, max_size=2**25, ping_interval=None) as ws:
                    self.ws = ws
                    self.connected = True
                    
                    if self.sid and self.seq:
                        await self.ws.send(json.dumps({"op": 6, "d": {"token": self.token, "session_id": self.sid, "seq": self.seq}}))
                    else:
                        await self.ws.send(json.dumps({"op": 2, "d": {"token": self.token, "properties": {"$os": "windows", "$browser": "chrome", "$device": "chrome"}, "intents": 33281}}))
                    
                    await self.listen()
            except:
                self.connected = False
                if self.hb_task: self.hb_task.cancel()
                await asyncio.sleep(3)

    async def listen(self):
        global username, userid, cookie_mgr
        async for msg in self.ws:
            try:
                e = json.loads(msg)
                op = e.get('op')
                
                if e.get('s'): self.seq = e['s']
                
                if op == 10:
                    hb = e['d']['heartbeat_interval']
                    self.url = e['d'].get('resume_gateway_url')
                    if self.hb_task: self.hb_task.cancel()
                    self.hb_task = asyncio.create_task(self.heartbeat(hb))
                    
                elif op == 0:
                    t = e['t']
                    
                    if t == 'READY':
                        self.sid = e['d']['session_id']
                        self.url = e['d']['resume_gateway_url']
                        os.system("cls" if os.name == "nt" else "clear")
                        print(f"{Fore.RED}╔════════════════════════════════════════╗")
                        print(f"║  FUSION ULTRA - {claim_mode.upper():^20}  ║")
                        print(f"╚════════════════════════════════════════╝{Fore.RESET}")
                        ok(f"Discord: {e['d']['user']['username']}")
                        ok(f"Roblox: {username} ({userid})")
                        ok(f"Cookies: {len(cookie_mgr.cookies)}")
                        
                        if claim_mode == "sequential":
                            print(f"{Fore.YELLOW}⚡ Sequential Mode: JOIN → wait → CLAIM")
                        else:
                            delays_str = " | ".join([f"{int(d*1000)}ms" for d in parallel_delays])
                            print(f"{Fore.YELLOW}⚡ Parallel Mode: 1 JOIN + {len(parallel_delays)} CLAIMs")
                            print(f"⚡ Delays: {delays_str}")
                        
                        print(f"⚡ Auto XCSRF refresh")
                        print(f"⚡ Chrome impersonation{Fore.RESET}\n")
                        
                        for g in e['d']['guilds']:
                            asyncio.create_task(self.load_guild(g["id"]))
                    
                    elif t == 'GUILD_CREATE':
                        asyncio.create_task(self.load_guild(e['d']['id']))
                    
                    elif t == 'MESSAGE_CREATE':
                        asyncio.create_task(self.handle_msg(e['d']))
                        
            except: pass

    async def handle_msg(self, d):
        global userid, username, cookie_mgr
        c = d.get("content", "")
        
        if c.startswith(prefix):
            a = str(d.get("author", {}).get("id"))
            if a == str(userid):
                ch = d.get("channel_id")
                if c == f"{prefix}stats":
                    await self.send(ch, f"📊 {stats['total']} | ✅ {stats['success']} | ❌ {stats['fail']} | 🍪 {len(cookie_mgr.cookies)}")
                elif c == f"{prefix}switch":
                    await switch_cookie()
                    await self.send(ch, f"✓ {username}")
            return
        
        c_lower = c.lower()
        if "roblox.com/group" in c_lower or "roblox.com/communit" in c_lower:
            m = re.search(r'(?:groups|communities)/(\d+)', c)
            if m:
                gid = int(m.group(1))
                asyncio.create_task(handle_claim(gid))

    async def send(self, ch, txt):
        global session
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: session.post(
                f"https://discord.com/api/v9/channels/{ch}/messages",
                json={"content": txt}, 
                headers={"authorization": self.token}
            ))
        except: pass

    async def load_guild(self, gid):
        try:
            if self.ws and self.connected:
                await self.ws.send(json.dumps({'op': 14, 'd': {'guild_id': gid, "typing": True, "activities": True}}))
        except: pass

    async def heartbeat(self, i):
        while self.connected:
            await asyncio.sleep(i / 1000)
            try:
                if self.ws and self.connected:
                    await self.ws.send(json.dumps({"op": 1, "d": self.seq}))
            except: break

# ==================== MAIN ====================
async def main():
    global username, cookie, session, cookie_mgr
    os.system("cls" if os.name == "nt" else "clear")
    
    init_session()
    await switch_cookie()
    
    if not cookie:
        fatal("No valid cookies!")
        return
    
    asyncio.create_task(xcsrf_refresher())
    log("XCSRF auto-refresh started")
    
    try:
        if claim_mode == "sequential":
            description = "**SEQUENTIAL MODE**\n⚡ JOIN → wait for completion → CLAIM\n⚡ Safe and stable strategy"
        else:
            delays_str = " | ".join([f"{int(d*1000)}ms" for d in parallel_delays])
            description = f"**PARALLEL MODE**\n⚡ 1 JOIN + {len(parallel_delays)} CLAIMs\n⚡ Delays: {delays_str}\n⚡ Multiple timing strategies"
        
        description += "\n⚡ Auto XCSRF refresh\n⚡ Chrome impersonation"
        
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: session.post(
            webhooks["logs"],
            json={
                "username": " Ultra Fusion",
                "embeds": [{
                    "title": "⚡ FUSION ULTRA STARTED",
                    "description": description,
                    "color": 0xFF0000,
                    "fields": [
                        {"name": "👤", "value": username, "inline": True},
                        {"name": "🍪", "value": str(len(cookie_mgr.cookies)), "inline": True},
                        {"name": "🔧 Mode", "value": claim_mode.upper(), "inline": True}
                    ],
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }]
            }
        ))
    except: pass
    
    client = Discord(token)
    await client.connect()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⚡ Stopped")
