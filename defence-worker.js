const THREAD_ID = 38636;
const GITHUB_OWNER = "dmrylezfree-beep";
const GITHUB_REPO = "travian-discord-bot";
const GITHUB_WORKFLOW = "defence_bot.yml";
const GITHUB_REF = "main";

// Discord WORLD Defence interface.
const DISCORD_APPLICATION_ID = "1555623257724682402";
const DISCORD_PUBLIC_KEY = "d1aa28732f54e287d78d859a69f21699794ba52da41c3b8f7da931aede02ce21";
const DISCORD_GUILD_ID = "1430982178074005507";
const DISCORD_DEFENCE_CHANNEL_ID = "1430982180401578153";
const WORLD_ALLIANCE_ID = 2;

function hexToBytes(hex) {
  if (!/^[0-9a-f]+$/i.test(hex) || hex.length % 2) throw new Error("Invalid hex");
  return Uint8Array.from(hex.match(/.{2}/g).map(x => parseInt(x, 16)));
}

async function verifyDiscordRequest(request, rawBody) {
  const signature = request.headers.get("X-Signature-Ed25519");
  const timestamp = request.headers.get("X-Signature-Timestamp");
  if (!signature || !timestamp) return false;
  try {
    const key = await crypto.subtle.importKey("raw", hexToBytes(DISCORD_PUBLIC_KEY), { name: "Ed25519" }, false, ["verify"]);
    const data = new TextEncoder().encode(timestamp + rawBody);
    return await crypto.subtle.verify("Ed25519", key, hexToBytes(signature), data);
  } catch (error) {
    console.error("Discord signature verification failed:", error);
    return false;
  }
}

async function registerDiscordCommands(env) {
  if (!env.DISCORD_BOT_TOKEN) throw new Error("Cloudflare: не задан DISCORD_BOT_TOKEN");
  const endpoint = `https://discord.com/api/v10/applications/${DISCORD_APPLICATION_ID}/guilds/${DISCORD_GUILD_ID}/commands`;
  const response = await fetch(endpoint, {
    method: "PUT",
    headers: {
      "Authorization": `Bot ${env.DISCORD_BOT_TOKEN}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify([
      {
        name: "def",
        description: "Открыть центр дефа WORLD",
        type: 1
      }
    ])
  });
  const details = await response.text();
  if (!response.ok) throw new Error(`Discord commands ${response.status}: ${details}`);
  return JSON.parse(details);
}


const DISCORD_PLAYERS_PATH = "data/defence/discord_players.json";
const TELEGRAM_PLAYERS_PATH = "data/defence/players.json";
const TRAVIAN_MAP_URL = "https://ts8.x1.asia.travian.com/map.sql";
const DTXT = {
 en:{choose:"Choose your language",reg:"Register",wait:"You are not registered yet.",title:"WORLD Defence registration",coord:"Village coordinates",hint:"Example: 22 63",bad:"❌ Enter coordinates as **22 63**.",miss:"❌ Village not found on the current Travian map.",world:"❌ This village does not belong to **WORLD**.",dup:"❌ This Travian account is already registered in Defence Bot.",done:"✅ **Registration complete**",account:"Travian account",village:"Village",tribe:"Tribe",active:"Active defence requests",none:"No active defence requests.",settings:"My settings",addVillage:"Add village",troops:"Troops",changeLang:"Language",arena:"Tournament Square",saved:"Saved",notYours:"❌ This village belongs to another Travian account.",err:"❌ Internal error. Please try again."},
 ja:{choose:"言語を選択してください",reg:"登録する",wait:"まだ登録されていません。",title:"WORLD Defence 登録",coord:"村の座標",hint:"例: 22 63",bad:"❌ 座標を **22 63** の形式で入力してください。",miss:"❌ 現在のTravianマップで村が見つかりません。",world:"❌ この村は **WORLD** 同盟に所属していません。",dup:"❌ このTravianアカウントは既にDefence Botに登録されています。",done:"✅ **登録が完了しました**",account:"Travianアカウント",village:"村",tribe:"種族",active:"防衛要請",none:"現在、防衛要請はありません。",settings:"設定",addVillage:"村を追加",troops:"兵士",changeLang:"言語",arena:"闘技場",saved:"保存しました",notYours:"❌ この村は別のTravianアカウントに所属しています。",err:"❌ 内部エラーが発生しました。"}
};
function dReply(content,components=[]){return Response.json({type:4,data:{content,components,flags:64}});}
function dUser(i){return String(i.member?.user?.id||i.user?.id||"");}
function langButtons(){return [{type:1,components:[{type:2,style:1,custom_id:"def_lang_en",label:"English",emoji:{name:"🇬🇧"}},{type:2,style:1,custom_id:"def_lang_ja",label:"日本語",emoji:{name:"🇯🇵"}}]}];}
function regButton(l){return [{type:1,components:[{type:2,style:3,custom_id:"def_register_"+l,label:DTXT[l].reg,emoji:{name:"🛡️"}}]}];}
function sendDefButtons(requests,l){return (requests||[]).slice(0,5).map(q=>({type:1,components:[{type:2,style:3,custom_id:"def_send_"+q.id+"_"+l,label:(l==="ja"?"防衛兵を送る #":"Send Defence #")+q.id,emoji:{name:"🛡️"}}]}));}
function publicCentreButtons(requests){return (requests||[]).slice(0,5).map(q=>({type:1,components:[{type:2,style:3,custom_id:"def_public_send_"+q.id,label:"🛡 Send Defence / 防衛兵を送る #"+q.id}]}));}
function publicCentreText(requests){const a=["🛡 **WORLD Defence**",""];if(!(requests||[]).length)a.push("No active defence requests / 現在、防衛要請はありません。");for(const q of requests||[]){a.push("🟢 **#"+q.id+"**  **"+q.target_x+"|"+q.target_y+"**","⚔️ "+(q.attack_time_display||q.attack_time),"🛡 "+Number(q.collected_def||0).toLocaleString()+" / "+Number(q.required_def||0).toLocaleString(),"");}return a.join("\n");}
function defenceThreadName(q){return ("🛡 DEF #"+q.id+" — "+q.target_x+"|"+q.target_y).slice(0,100);}
function defenceThreadText(q){
 const required=Number(q.required_def||0),collected=Number(q.collected_def||0),missing=Math.max(0,required-collected);
 return [
  "🛡 **DEFENCE REQUEST #"+q.id+" / 防衛要請 #"+q.id+"**","",
  "🎯 **"+q.target_x+"|"+q.target_y+"**",
  "⚔️ **Attack / 攻撃:** "+(q.attack_time_display||q.attack_time),
  "",
  "🛡 **REQUEST / 必要:** "+required.toLocaleString(),
  "✅ **SENT / 送信済み:** "+collected.toLocaleString(),
  "🔴 **STILL NEED / 不足:** "+missing.toLocaleString()
 ].join("\n");
}
function defenceThreadComponents(q){
 if(q.status!=="active"||Number(q.collected_def||0)>=Number(q.required_def||0))return [];
 return [{type:1,components:[{type:2,style:3,custom_id:"def_public_send_"+q.id,label:"🛡 Send Defence / 防衛兵を送る"}]}];
}
async function defenderRole(env){
 const roles=await discordApi(env,"/guilds/"+DISCORD_GUILD_ID+"/roles");
 return (roles||[]).find(r=>String(r.name||"").toLowerCase()==="defender")||null;
}
async function findDefenceThread(env,q){
 try{
  const active=await discordApi(env,"/guilds/"+DISCORD_GUILD_ID+"/threads/active");
  let t=(active?.threads||[]).find(x=>String(x.name||"")===defenceThreadName(q));
  if(t)return t;
 }catch(e){console.error("Discord active threads read failed:",e);}
 try{
  const archived=await discordApi(env,"/channels/"+DISCORD_DEFENCE_CHANNEL_ID+"/threads/archived/public?limit=100");
  return (archived?.threads||[]).find(x=>String(x.name||"")===defenceThreadName(q))||null;
 }catch(e){console.error("Discord archived threads read failed:",e);return null;}
}
async function syncDefenceThreads(env,requests,allRequests=[]){
 const role=await defenderRole(env).catch(e=>{console.error("Defender role lookup failed:",e);return null;});
 const activeIds=new Set((requests||[]).map(q=>Number(q.id)));
 // Close threads whose request is no longer actionable (covered, cancelled or expired).
 for(const q of allRequests||[]){
  if(activeIds.has(Number(q.id)))continue;
  const thread=await findDefenceThread(env,q);
  if(!thread)continue;
  try{
   const messages=await discordApi(env,"/channels/"+thread.id+"/messages?limit=50");
   const cards=(messages||[]).filter(m=>String(m.author?.id||"")===DISCORD_APPLICATION_ID&&String(m.content||"").startsWith("🛡 **DEFENCE REQUEST #"+q.id));
   const card=cards[0];
   const status=Number(q.collected_def||0)>=Number(q.required_def||0)?"✅ COVERED / 防衛完了":q.status!=="active"?"⛔ CLOSED / 終了":"⌛ EXPIRED / 期限切れ";
   const body={content:defenceThreadText(q)+"\n\n"+status,components:[],allowed_mentions:{parse:[]}};
   if(card)await discordApi(env,"/channels/"+thread.id+"/messages/"+card.id,"PATCH",body);
   else await discordApi(env,"/channels/"+thread.id+"/messages","POST",body);
   for(const duplicate of cards.slice(1)){
    try{await discordApi(env,"/channels/"+thread.id+"/messages/"+duplicate.id,"DELETE");}
    catch(e){console.error("Duplicate defence card delete failed #"+q.id+":",e);}
   }
   await discordApi(env,"/channels/"+thread.id,"PATCH",{archived:true});
  }catch(e){console.error("Defence thread close failed #"+q.id+":",e);}
 }
 for(const q of requests||[]){
  let thread=await findDefenceThread(env,q);
  if(!thread){
   const starter=await discordApi(env,"/channels/"+DISCORD_DEFENCE_CHANNEL_ID+"/messages","POST",{
    content:"🛡 **New defence request / 新しい防衛要請**\n🎯 **"+q.target_x+"|"+q.target_y+"**",
    allowed_mentions:{parse:[]}
   });
   thread=await discordApi(env,"/channels/"+DISCORD_DEFENCE_CHANNEL_ID+"/messages/"+starter.id+"/threads","POST",{name:defenceThreadName(q),auto_archive_duration:1440});
   // Notify defenders only after the request thread exists, so the mention
   // belongs to the actual defence discussion rather than the parent channel.
   if(role)await discordApi(env,"/channels/"+thread.id+"/messages","POST",{
    content:"<@&"+role.id+"> 🛡 **New defence request / 新しい防衛要請**",
    allowed_mentions:{roles:[role.id]}
   });
  }
  try{
   if(thread.thread_metadata?.archived)await discordApi(env,"/channels/"+thread.id,"PATCH",{archived:false});
   const messages=await discordApi(env,"/channels/"+thread.id+"/messages?limit=50");
   const cards=(messages||[]).filter(m=>String(m.author?.id||"")===DISCORD_APPLICATION_ID&&String(m.content||"").startsWith("🛡 **DEFENCE REQUEST #"+q.id));
   const card=cards[0];
   const body={content:defenceThreadText(q),components:defenceThreadComponents(q),allowed_mentions:{parse:[]}};
   if(card)await discordApi(env,"/channels/"+thread.id+"/messages/"+card.id,"PATCH",body);
   else await discordApi(env,"/channels/"+thread.id+"/messages","POST",body);
   for(const duplicate of cards.slice(1)){
    try{await discordApi(env,"/channels/"+thread.id+"/messages/"+duplicate.id,"DELETE");}
    catch(e){console.error("Duplicate defence card delete failed #"+q.id+":",e);}
   }
  }catch(e){console.error("Defence thread sync failed #"+q.id+":",e);}
 }
}

async function discordApi(env,path,method="GET",body=null){if(!env.DISCORD_BOT_TOKEN)throw new Error("Cloudflare: DISCORD_BOT_TOKEN is not set");const opts={method,headers:{"Authorization":"Bot "+env.DISCORD_BOT_TOKEN}};if(body!==null){opts.headers["Content-Type"]="application/json";opts.body=JSON.stringify(body);}const r=await fetch("https://discord.com/api/v10"+path,opts);const txt=await r.text();if(!r.ok)throw new Error("Discord API "+method+" "+path+" "+r.status+": "+txt);return txt?JSON.parse(txt):{};}
async function findDiscordCentre(env){
 let pins=[];
 try{pins=await discordApi(env,"/channels/"+DISCORD_DEFENCE_CHANNEL_ID+"/pins");}catch(e){console.error("Discord pins read failed",e);}
 let centre=(pins||[]).find(m=>String(m.author?.id||"")===DISCORD_APPLICATION_ID&&String(m.content||"").startsWith("🛡 **WORLD Defence**"));
 if(centre)return centre;
 // Discord's pins response can be stale/changed across API versions. Fall back
 // to recent channel messages so /def edits the existing centre instead of
 // silently creating or missing it.
 try{
  const recent=await discordApi(env,"/channels/"+DISCORD_DEFENCE_CHANNEL_ID+"/messages?limit=50");
  centre=(recent||[]).find(m=>String(m.author?.id||"")===DISCORD_APPLICATION_ID&&String(m.content||"").startsWith("🛡 **WORLD Defence**"));
 }catch(e){console.error("Discord centre history read failed",e);}
 return centre||null;
}
async function refreshDiscordCentre(env){
 const requests=await loadActiveRequests(env);
 let allRequests=[];try{const rq=await ghJson(env,"data/defence/requests.json");allRequests=Array.isArray(rq.data)?rq.data:[];}catch(e){console.error("All defence requests load failed:",e);}
 // Restore the public centre first. Thread creation is secondary and must not
 // prevent the visible centre from recovering after Discord messages are deleted.
 const body={content:publicCentreText(requests),components:publicCentreButtons(requests),allowed_mentions:{parse:[]}};
 const centre=await findDiscordCentre(env);
 let messageId;
 if(centre){
  const updated=await discordApi(env,"/channels/"+DISCORD_DEFENCE_CHANNEL_ID+"/messages/"+centre.id,"PATCH",body);
  try{await discordApi(env,"/channels/"+DISCORD_DEFENCE_CHANNEL_ID+"/pins/"+centre.id,"PUT");}catch(e){console.error("Discord centre re-pin failed:",e);}
  messageId=updated?.id||centre.id;
  console.log("Discord defence centre refreshed:",centre.id);
 }else{
  const m=await discordApi(env,"/channels/"+DISCORD_DEFENCE_CHANNEL_ID+"/messages","POST",body);
  if(!m?.id)throw new Error("Discord centre message was not created");
  messageId=m.id;
  try{await discordApi(env,"/channels/"+DISCORD_DEFENCE_CHANNEL_ID+"/pins/"+m.id,"PUT");}catch(e){console.error("Discord centre pin failed:",e);}
  console.log("Discord defence centre created:",m.id);
 }
 try{await syncDefenceThreads(env,requests,allRequests);}catch(e){console.error("Discord thread rebuild failed:",e);}
 return messageId;
}
function ghDecode(s){const b=atob(String(s||"").replace(/\s/g,""));return new TextDecoder().decode(Uint8Array.from(b,x=>x.charCodeAt(0)));}
function ghEncode(s){const a=new TextEncoder().encode(s);let b="";for(let i=0;i<a.length;i+=32768)b+=String.fromCharCode(...a.subarray(i,i+32768));return btoa(b);}
async function ghJson(env,path){const u="https://api.github.com/repos/"+GITHUB_OWNER+"/"+GITHUB_REPO+"/contents/"+path+"?ref="+GITHUB_REF;const r=await fetch(u,{headers:{Authorization:"Bearer "+env.GITHUB_TOKEN,Accept:"application/vnd.github+json","User-Agent":"travian-defence"}});if(!r.ok)throw new Error("GitHub "+path+" "+r.status);const p=await r.json();return {data:JSON.parse(ghDecode(p.content)),sha:p.sha};}
async function ghSave(env,path,data,sha,msg){const u="https://api.github.com/repos/"+GITHUB_OWNER+"/"+GITHUB_REPO+"/contents/"+path;const r=await fetch(u,{method:"PUT",headers:{Authorization:"Bearer "+env.GITHUB_TOKEN,Accept:"application/vnd.github+json","Content-Type":"application/json","User-Agent":"travian-defence"},body:JSON.stringify({message:msg,content:ghEncode(JSON.stringify(data,null,2)+"\n"),sha,branch:GITHUB_REF})});if(!r.ok)throw new Error("GitHub save "+path+" "+r.status+": "+await r.text());}
function sqlFields(row){let o=[],v="",q=false;for(let i=0;i<row.length;i++){const ch=row[i];if(ch==="'"){if(q&&row[i+1]==="'"){v+="'";i++;}else q=!q;}else if(ch===","&&!q){o.push(v.trim());v="";}else v+=ch;}o.push(v.trim());return o;}
function mapVillage(text,x,y){const rows=text.match(/\([^;\n]*?\)(?=,|;|\s*$)/g)||[];for(const row of rows){const f=sqlFields(row.slice(1,-1));if(f.length>=10&&Number(f[1])===x&&Number(f[2])===y)return {uid:Number(f[6]),name:f[5],player:f[7],aid:Number(f[8])||0,tribe:Number(f[3])};}return null;}
async function getMap(){const r=await fetch(TRAVIAN_MAP_URL,{headers:{"User-Agent":"travian-defence"}});if(!r.ok)throw new Error("map.sql "+r.status);return r.text();}
function tribeName(n,l){const a=l==="ja"?{1:"ローマン",2:"チュートン",3:"ガウル",6:"エジプト",7:"フン",8:"スパルタ"}:{1:"Romans",2:"Teutons",3:"Gauls",6:"Egyptians",7:"Huns",8:"Spartans"};return a[n]||String(n);}
async function uidUsed(env,uid,dp,myId,map){for(const [id,p] of Object.entries(dp))if(id!==myId&&Number(p?.travian_uid)===uid)return true;const tp=(await ghJson(env,TELEGRAM_PLAYERS_PATH)).data||{};for(const p of Object.values(tp)){if(Number(p?.travian_uid)===uid)return true;for(const v of p?.villages||[]){const m=String(v.coordinates||"").match(/^\s*(-?\d+)\s+(-?\d+)\s*$/);if(m&&mapVillage(map,+m[1],+m[2])?.uid===uid)return true;}}return false;}
async function centreData(env,p){const l=p.language==="ja"?"ja":"en",t=DTXT[l];let rs=[];try{rs=await loadActiveRequests(env);}catch{}let a=["🛡 **WORLD Defence**","","👤 **"+t.account+":** "+p.player_name,"🏘 **"+t.village+":** "+(p.villages?.[0]?.coordinates||"—"),"⚔️ **"+t.tribe+":** "+tribeName(p.tribe,l),"","**"+t.active+":**"];if(!rs.length)a.push(t.none);for(const q of rs)a.push("🟢 **#"+q.id+"** — "+q.target_x+"|"+q.target_y+" — 🛡 "+Number(q.collected_def||0).toLocaleString()+"/"+Number(q.required_def||0).toLocaleString()+" — ⚔️ "+(q.attack_time_display||q.attack_time));return {text:a.join("\n"),requests:rs,lang:l};}


const DEF_UNITS={
 roman:[["legionnaire","Legionnaire","レジョネア"],["praetorian","Praetorian","プレトリアン"],["equites_caesaris","Equites Caesaris","エクイーツ・カエザリス"]],
 teuton:[["spearman","Spearman","スピアマン"],["paladin","Paladin","パラディン"]],
 gaul:[["phalanx","Phalanx","ファランクス"],["druidrider","Druidrider","ドルイドライダー"],["haeduan","Haeduan","ヘジュアン"]]
};
const DEF_SPEEDS={legionnaire:6,praetorian:5,equites_caesaris:10,spearman:7,paladin:10,phalanx:7,druidrider:16,haeduan:13};
const DEF_CAV=new Set(["equites_caesaris","paladin","druidrider","haeduan"]);
function parseServerTime(s){const m=String(s||"").match(/^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})$/);return m?Date.UTC(+m[1],+m[2]-1,+m[3],+m[4],+m[5],+m[6]):NaN;}
function formatServerTime(ms){const d=new Date(ms);return d.getUTCFullYear()+"-"+String(d.getUTCMonth()+1).padStart(2,"0")+"-"+String(d.getUTCDate()).padStart(2,"0")+" "+String(d.getUTCHours()).padStart(2,"0")+":"+String(d.getUTCMinutes()).padStart(2,"0")+":"+String(d.getUTCSeconds()).padStart(2,"0");}
function timeOnly(s){return String(s||"").split(" ")[1]||String(s||"");}
function mapDist(x1,y1,x2,y2){let dx=Math.abs(x2-x1),dy=Math.abs(y2-y1);dx=Math.min(dx,401-dx);dy=Math.min(dy,401-dy);return Math.sqrt(dx*dx+dy*dy);}
function travelSecs(distance,speed,arena=0){const first=Math.min(distance,20),second=Math.max(0,distance-20);return first*3600/speed+(second?second*3600/(speed*(1+Number(arena||0)*0.20)):0);}
function heroInventory(p){const inv=p.hero_inventory||{};return {standards:[...new Set((inv.standards||[]).map(Number).filter(x=>x>0))].sort((a,b)=>a-b),boots:[...new Set((inv.boots||[]).map(Number).filter(x=>x>0))].sort((a,b)=>a-b),maps:[...new Set((inv.maps||[]).map(Number).filter(x=>x>0))].sort((a,b)=>a-b)};}
function heroTravelSecs(distance,speed,arena,standard=0,boots=0){const base=speed*(1+standard/100),first=Math.min(distance,20),second=Math.max(0,distance-20);return first*3600/base+(second?second*3600/(base*(1+Number(arena||0)*0.20+boots/100)):0);}
function heroRoutes(p,v,distance,speed){
 if(!v.hero?.present)return[];
 const inv=heroInventory(p),standards=[0,...inv.standards],boots=[0,...inv.boots],bestMap=Math.max(0,...inv.maps),out=[];
 for(const std of standards)for(const boot of boots){
  const seconds=heroTravelSecs(distance,speed,v.arena,std,boot);
  const parts=["🦸 Hero"];if(std)parts.push("🚩 +"+std+"%");else if(bestMap)parts.push("🗺 +"+bestMap+"%");if(boot)parts.push("🥾 +"+boot+"%");
  const route={seconds,standard:std,boots:boot,map:std?0:bestMap,label:parts.join(" · ")};
  const old=out.find(x=>Math.round(x.seconds)===Math.round(seconds)&&x.standard===std);
  if(old){if(boot>old.boots)out.splice(out.indexOf(old),1,route);}else out.push(route);
 }
 return out;
}
function discordVillageOptions(p,q){
 const attack=parseServerTime(q.attack_time),now=parseServerTime(serverNowText());if(!Number.isFinite(attack)||attack<=now)return[];
 const out=[];
 for(let idx=0;idx<(p.villages||[]).length;idx++){
  const v=p.villages[idx],m=String(v.coordinates||"").match(/^\s*(-?\d+)\s+(-?\d+)\s*$/);if(!m)continue;
  const dist=mapDist(+m[1],+m[2],Number(q.target_x),Number(q.target_y)),units=[];
  for(const u of DEF_UNITS[p.race]||[]){const key=u[0],amount=Number(v.troops?.[key]||0),speed=DEF_SPEEDS[key];if(amount>0&&speed)units.push({key,amount,speed,value:DEF_CAV.has(key)?2:1});}
  if(!units.length)continue;
  const routes=[{mode:"normal",gear_label:"⚡ No hero",standard:0,boots:0,map:0,calc:(u)=>travelSecs(dist,u.speed,v.arena)}];
  if(v.hero?.present){
   // Build gear choices from the slowest configured unit, matching Telegram's
   // convoy timing: the whole defence travels at the slowest included speed.
   const slowest=Math.min(...units.map(u=>u.speed));
   for(const h of heroRoutes(p,v,dist,slowest))routes.push({mode:"hero",gear_label:h.label,standard:h.standard,boots:h.boots,map:h.map,calc:(u)=>heroTravelSecs(dist,u.speed,v.arena,h.standard,h.boots)});
  }
  for(let routeIdx=0;routeIdx<routes.length;routeIdx++){
   const route=routes[routeIdx],eligible=units.map(u=>({...u,seconds:route.calc(u)})).filter(u=>now+u.seconds*1000<=attack);
   if(!eligible.length)continue;
   const seconds=Math.max(...eligible.map(u=>u.seconds)),deadline=formatServerTime(attack-seconds*1000),maxDef=eligible.reduce((s,u)=>s+u.amount*u.value,0);
   out.push({idx,routeIdx,village:v,distance:dist,deadline,maxDef,speed_mode:route.mode,gear_label:route.gear_label,standard:route.standard,boots:route.boots,map:route.map});
  }
 }
 return out;
}
function sendSourceButtons(p,q,l){
 const opts=discordVillageOptions(p,q),rows=opts.slice(0,4).map(o=>({type:1,components:[{type:2,style:o.speed_mode==="hero"?3:1,custom_id:"def_src_"+q.id+"_"+o.idx+"_"+o.routeIdx+"_"+l,label:(o.speed_mode==="hero"?"🦸 ":"🏘 ")+String(o.village.coordinates).replace(" ","|")+" · "+timeOnly(o.deadline)}]}));
 rows.push({type:1,components:[{type:2,style:2,custom_id:"def_srcskip_"+q.id+"_"+l,label:l==="ja"?"村を選ばずに確認":"Confirm without village"}]});return rows;
}
function sendSourceText(p,q,l){
 const opts=discordVillageOptions(p,q);let a=[l==="ja"?"🛡 **送信方法（任意）**":"🛡 **Departure option (optional)**","",l==="ja"?"保存された兵士、闘技場、英雄装備から送信期限を計算します。":"Departure deadline uses saved troops, Tournament Square and hero gear."];
 if(!opts.length)a.push("",l==="ja"?"⚪ 時間を計算できる方法がありません。村を選ばずに確認できます。":"⚪ No configured route can be timed. You can still confirm without a village.");
 else for(const o of opts.slice(0,8))a.push((o.speed_mode==="hero"?"🦸":"🏘")+" **"+String(o.village.coordinates).replace(" ","|")+"** · "+o.gear_label+" · 🚨 "+timeOnly(o.deadline)+" · 🛡 ≤"+o.maxDef);
 a.push("",l==="ja"?"方法を選ぶか、村を選ばずに確認してください。":"Choose a departure option, or confirm without selecting one.");return a.join("\n");
}
async function saveDiscordPledge(env,p,id,rid,l,n,sourceIdx=null,routeIdx=0){const rq=await ghJson(env,"data/defence/requests.json"),list=Array.isArray(rq.data)?rq.data:[],q=list.find(x=>Number(x.id)===rid);if(!q||q.status!=="active")return {error:l==="ja"?"❌ この防衛要請は終了しています。":"❌ This defence request is no longer active."};const remaining=Math.max(0,Number(q.required_def||0)-Number(q.collected_def||0));if(remaining<=0)return {error:l==="ja"?"✅ この防衛要請は既に完了しています。":"✅ This defence request is already covered."};const amount=Math.min(n,remaining),plan=[];if(sourceIdx!==null){const o=discordVillageOptions(p,q).find(x=>x.idx===sourceIdx&&x.routeIdx===routeIdx);if(!o)return {error:l==="ja"?"❌ この村は時間内に到着できません。":"❌ This village can no longer arrive in time."};const reminder=formatServerTime(parseServerTime(o.deadline)-5*60*1000);plan.push({village_idx:o.idx,village:o.village.coordinates,def_points:amount,speed_mode:o.speed_mode,gear_label:o.gear_label,standard:o.standard||0,boots:o.boots||0,map:o.map||0,deadline_at:o.deadline,deadline:timeOnly(o.deadline),reminder_at:reminder,reminder_time:timeOnly(reminder),reminder_sent:false});}q.contributions=Array.isArray(q.contributions)?q.contributions:[];q.contributions.push({platform:"discord",user_id:id,player_name:p.player_name,def_points:amount,plan,created_at:serverNowText()});q.collected_def=q.contributions.reduce((s,z)=>s+Number(z.def_points||0),0);await ghSave(env,"data/defence/requests.json",list,rq.sha,"Add WORLD Discord defence contribution");if(plan.length){await queueReminder(env,{platform:"discord",discord_id:id,language:l,request_id:q.id,target_x:q.target_x,target_y:q.target_y,attack_time:q.attack_time,attack_time_display:q.attack_time_display,village:plan[0].village,def_points:amount,speed_mode:plan[0].speed_mode,gear_label:plan[0].gear_label,deadline:plan[0].deadline,deadline_at:plan[0].deadline_at,reminder_at:plan[0].reminder_at});}await dispatchDiscordSync(env);await refreshDiscordCentre(env);return {q,amount,plan};}
function canCreateDefence(i){try{return (BigInt(String(i.member?.permissions||"0"))&8192n)!==0n;}catch{return false;}}
function createRequestButton(l){return [{type:1,components:[{type:2,style:3,custom_id:"def_create_"+l,label:l==="ja"?"➕ 防衛要請を作成":"➕ Create defence request"}]}];}
function ownActiveRequests(requests,userId){return (requests||[]).filter(q=>q.status==="active"&&q.requester_platform==="discord"&&String(q.requester_id||"")===String(userId||""));}
function deleteRequestButton(requests,l,userId){
 const own=ownActiveRequests(requests,userId);
 if(!own.length)return [];
 return [{type:1,components:[{type:2,style:4,custom_id:"def_delete_menu_"+l,label:l==="ja"?"🗑 自分の要請を削除":"🗑 Delete my request"}]}];
}
function deleteRequestChoices(requests,l,userId){
 return ownActiveRequests(requests,userId).slice(0,5).map(q=>({type:1,components:[{type:2,style:4,custom_id:"def_delete_"+q.id+"_"+l,label:"#"+q.id+" — "+q.target_x+"|"+q.target_y}]}));
}
function personalCentreComponents(requests,l,canCreate=false,userId=""){
 const fixed=[...(canCreate?createRequestButton(l):[]),...deleteRequestButton(requests,l,userId),...settingsButtons(l)];
 const room=Math.max(0,5-fixed.length);
 return [...(sendDefButtons(requests,l).slice(0,room)),...fixed];
}
function settingsButtons(l){const t=DTXT[l];return [{type:1,components:[{type:2,style:1,custom_id:"def_add_"+l,label:t.addVillage,emoji:{name:"🏘️"}},{type:2,style:1,custom_id:"def_troops_"+l,label:t.troops,emoji:{name:"🛡️"}}]},{type:1,components:[{type:2,style:1,custom_id:"def_hero_"+l,label:l==="ja"?"英雄と装備":"Hero & gear",emoji:{name:"🦸"}},{type:2,style:2,custom_id:"def_language",label:t.changeLang,emoji:{name:"🌐"}}]}];}
function villageButtons(p,l){return (p.villages||[]).slice(0,5).map((v,n)=>({type:1,components:[{type:2,style:1,custom_id:"def_village_"+n+"_"+l,label:(v.name||("Village "+(n+1)))+" ("+String(v.coordinates).replace(" ","|")+")"}]}));}
function unitButtons(p,idx,l){const us=DEF_UNITS[p.race]||[];return us.map(u=>({type:1,components:[{type:2,style:1,custom_id:"def_unit_"+idx+"_"+u[0]+"_"+l,label:(l==="ja"?u[2]:u[1])+" — "+Number(p.villages?.[idx]?.troops?.[u[0]]||0)}]}));}

async function handleDiscord(request, env, ctx) {
 const raw=await request.text();
 if(!(await verifyDiscordRequest(request,raw)))return new Response("Invalid request signature",{status:401});
 let i;try{i=JSON.parse(raw);}catch{return new Response("Bad Request",{status:400});}
 if(i.type===1)return Response.json({type:1});
 if(String(i.guild_id||"")!==DISCORD_GUILD_ID)return dReply("❌ WORLD Defence is available only in the WORLD server.\n❌ WORLD DefenceはWORLDサーバーでのみ利用できます。");
 // Interactions are allowed both in the main defence channel and in threads
 // created under it. Discord reports the thread ID as channel_id, so rejecting
 // every ID except the parent channel broke Send Defence inside request threads.
 if(String(i.channel_id||"")!==DISCORD_DEFENCE_CHANNEL_ID){
   // Interaction payloads from a thread normally already contain parent_id.
   // Avoid an extra Discord REST round-trip: modal submissions must be
   // acknowledged within Discord's short interaction deadline.
   let parentId=String(i.channel?.parent_id||"");
   if(!parentId){
     let interactionChannel=null;
     try{interactionChannel=await discordApi(env,"/channels/"+String(i.channel_id||""));}catch(e){console.error("Discord interaction channel lookup failed:",e);}
     parentId=String(interactionChannel?.parent_id||"");
   }
   if(parentId!==DISCORD_DEFENCE_CHANNEL_ID)
     return dReply("❌ WORLD Defence is available only in the designated defence channel and its request threads.\n❌ WORLD Defenceは指定された防衛チャンネルとその防衛スレッドでのみ利用できます。");
 }
 const id=dUser(i);

 // Fast path for the whole defence-send flow. Never wait for GitHub before
 // acknowledging a Discord interaction.
 const cid=String(i.data?.custom_id||"");
 if(i.type===3&&/^def_delete_menu_(en|ja)$/.test(cid)){
   const l=cid.endsWith("_ja")?"ja":"en";
   // This branch runs before the normal profile-loading block below, so load
   // the Discord player explicitly here. Referencing p here previously threw
   // before Discord could be acknowledged, causing "application did not respond".
   const playerLoaded=await ghJson(env,DISCORD_PLAYERS_PATH),p=(playerLoaded.data||{})[id];
   if(!p?.travian_uid)return dReply(l==="ja"?"❌ まず **/def** で登録してください。":"❌ Please register first with **/def**.");
   const rs=await loadActiveRequests(env),own=ownActiveRequests(rs,id);
   if(!own.length)return dReply(l==="ja"?"🗑 削除できる自分の防衛要請はありません。":"🗑 You have no active defence requests to delete.");
   return dReply(l==="ja"?"🗑 **削除する自分の防衛要請を選択してください:**":"🗑 **Choose your defence request to delete:**",deleteRequestChoices(rs,l,id));
 }
 if(i.type===3&&/^def_delete_\d+_(en|ja)$/.test(cid)){
   const a=cid.split("_"),rid=Number(a[2]),l=a[3]==="ja"?"ja":"en";
   const rs=await loadActiveRequests(env),q=(rs||[]).find(x=>Number(x.id)===rid);
   if(!q||q.requester_platform!=="discord"||String(q.requester_id||"")!==id)
     return dReply(l==="ja"?"❌ この防衛要請を削除する権限がありません。":"❌ You can only delete your own defence request.");
   return dReply(
     (l==="ja"?"⚠️ **この防衛要請を削除しますか？**":"⚠️ **Delete this defence request?**")+"\n#"+q.id+" — "+q.target_x+"|"+q.target_y,
     [{type:1,components:[
       {type:2,style:4,custom_id:"def_delete_confirm_"+q.id+"_"+l,label:l==="ja"?"削除する":"Delete"},
       {type:2,style:2,custom_id:"def_delete_cancel_"+l,label:l==="ja"?"キャンセル":"Cancel"}
     ]}]
   );
 }
 if(i.type===3&&/^def_delete_cancel_(en|ja)$/.test(cid)){
   const l=cid.endsWith("_ja")?"ja":"en";
   const playerLoaded=await ghJson(env,DISCORD_PLAYERS_PATH),p=(playerLoaded.data||{})[id];
   if(!p?.travian_uid)return dReply(l==="ja"?"❌ まず **/def** で登録してください。":"❌ Please register first with **/def**.");
   const cd=await centreData(env,p);
   return dReply(cd.text,personalCentreComponents(cd.requests,l,canCreateDefence(i),id));
 }
 if(i.type===3&&/^def_delete_confirm_\d+_(en|ja)$/.test(cid)){
   const a=cid.split("_"),rid=Number(a[3]),l=a[4]==="ja"?"ja":"en",token=i.token,appId=i.application_id;
   ctx.waitUntil((async()=>{let content,components=[];try{
     const rq=await ghJson(env,"data/defence/requests.json"),list=Array.isArray(rq.data)?rq.data:[],q=list.find(x=>Number(x.id)===rid);
     if(!q||q.status!=="active"||q.requester_platform!=="discord"||String(q.requester_id||"")!==id){
       content=l==="ja"?"❌ この防衛要請を削除する権限がないか、既に終了しています。":"❌ You can only delete your own active defence request.";
     }else{
       q.status="cancelled";q.cancelled_at=serverNowText();q.cancelled_by_platform="discord";q.cancelled_by_id=id;
       await ghSave(env,"data/defence/requests.json",list,rq.sha,"Cancel WORLD Discord defence request #"+rid);
       await dispatchDiscordSync(env);await refreshDiscordCentre(env);
       content=(l==="ja"?"✅ **防衛要請 #":"✅ **Defence request #")+rid+(l==="ja"?" を削除しました。**":" deleted.**");
       try{const cd=await centreData(env,p);components=personalCentreComponents(cd.requests,l,canCreateDefence(i),id);}catch{}
     }
   }catch(e){console.error("Deferred request deletion failed:",e);content=l==="ja"?"❌ 要請を削除できませんでした。もう一度お試しください。":"❌ Could not delete the request. Please try again.";}
   await fetch("https://discord.com/api/v10/webhooks/"+appId+"/"+token+"/messages/@original",{method:"PATCH",headers:{"content-type":"application/json"},body:JSON.stringify({content,components})});
   })());
   return Response.json({type:5,data:{flags:64}});
 }
 if(i.type===3&&/^def_create_(en|ja)$/.test(cid)){
   const l=cid.endsWith("_ja")?"ja":"en";
   if(!canCreateDefence(i))return dReply(l==="ja"?"❌ この操作には「メッセージの管理」権限が必要です。":"❌ Manage Messages permission is required to create defence requests.");
   return Response.json({type:9,data:{custom_id:"def_createval_"+l,title:l==="ja"?"防衛要請を作成":"Create defence request",components:[
    {type:1,components:[{type:4,custom_id:"coords",style:1,label:l==="ja"?"対象座標":"Target coordinates",placeholder:"64 65",required:true,max_length:9}]},
    {type:1,components:[{type:4,custom_id:"attack",style:1,label:l==="ja"?"攻撃時刻 (YYYY-MM-DD HH:MM:SS)":"Attack time (YYYY-MM-DD HH:MM:SS)",placeholder:"2026-10-03 20:30:00",required:true,max_length:19}]},
    {type:1,components:[{type:4,custom_id:"required",style:1,label:l==="ja"?"必要防衛ポイント":"Required defence points",placeholder:"50000",required:true,max_length:9}]}
   ]}});
 }
 if(i.type===5&&/^def_createval_(en|ja)$/.test(cid)){
   const l=cid.endsWith("_ja")?"ja":"en";
   if(!canCreateDefence(i))return dReply(l==="ja"?"❌ 権限がありません。":"❌ You do not have permission.");
   const vals=Object.fromEntries((i.data.components||[]).map(x=>x.components?.[0]).filter(Boolean).map(x=>[x.custom_id,String(x.value||"").trim()]));
   const cm=vals.coords?.match(/^(-?\d{1,3})\s+(-?\d{1,3})$/),attack=vals.attack||"",required=Number(vals.required);
   if(!cm||+cm[1]<-200||+cm[1]>200||+cm[2]<-200||+cm[2]>200||!/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(attack)||!Number.isInteger(required)||required<=0)
     return dReply(l==="ja"?"❌ 座標、時刻、必要防衛ポイントを確認してください。":"❌ Check coordinates, attack time and required defence points.");
   const attackMs=parseServerTime(attack);if(!Number.isFinite(attackMs)||attackMs<=parseServerTime(serverNowText()))return dReply(l==="ja"?"❌ 攻撃時刻は未来である必要があります。":"❌ Attack time must be in the future.");
   const token=i.token,appId=i.application_id,x=+cm[1],y=+cm[2],creator=id,uname=i.member?.user?.username||"",gname=i.member?.user?.global_name||"";
   ctx.waitUntil((async()=>{let content;try{
    const map=await getMap(),v=mapVillage(map,x,y);
    if(!v||v.aid!==WORLD_ALLIANCE_ID)content=l==="ja"?"❌ 対象はWORLD同盟の村である必要があります。":"❌ Target must be a WORLD alliance village.";
    else{
     const rq=await ghJson(env,"data/defence/requests.json"),list=Array.isArray(rq.data)?rq.data:[],rid=Math.max(0,...list.map(z=>Number(z.id)||0))+1;
     const q={id:rid,requester_platform:"discord",requester_id:creator,requester_username:uname,requester_first_name:gname,target_x:x,target_y:y,target_player:v.player,attack_time:attack,attack_time_display:attack.replace(/^(\d{4})-(\d{2})-(\d{2}) /,"$3.$2.$1 "),required_def:required,collected_def:0,status:"active",contributions:[],created_at:serverNowText()};
     await ghSave(env,"data/defence/requests.json",[...list,q],rq.sha,"Create WORLD Discord defence request #"+rid);
     await queueDiscordExpiry(env,q);
     await dispatchDiscordSync(env);await refreshDiscordCentre(env);
     content=(l==="ja"?"✅ **防衛要請を作成しました #":"✅ **Defence request created #")+rid+"**\n🎯 **"+x+"|"+y+"**\n⚔️ "+q.attack_time_display+"\n🛡 "+required.toLocaleString();
    }
   }catch(e){console.error("Deferred request creation failed:",e);content=l==="ja"?"❌ 要請を作成できませんでした。もう一度お試しください。":"❌ Could not create the request. Please try again.";}
   await fetch("https://discord.com/api/v10/webhooks/"+appId+"/"+token+"/messages/@original",{method:"PATCH",headers:{"content-type":"application/json"},body:JSON.stringify({content,components:[]})});
   })());
   return Response.json({type:5,data:{flags:64}});
 }
 if(i.type===3&&/^def_public_send_\d+$/.test(cid)){
   const rid=Number(cid.split("_")[3]),l="en";
   return Response.json({type:9,data:{custom_id:"def_sendamount_"+rid+"_"+l,title:"Send Defence",components:[{type:1,components:[{type:4,custom_id:"amount",style:1,label:"Defence points",placeholder:"1000",required:true,min_length:1,max_length:8}]}]}});
 }
 if(i.type===3&&/^def_send_\d+_(en|ja)$/.test(cid)){
   const a=cid.split("_"),rid=Number(a[2]),l=a[3]==="ja"?"ja":"en";
   return Response.json({type:9,data:{custom_id:"def_sendamount_"+rid+"_"+l,title:l==="ja"?"防衛兵を送る":"Send Defence",components:[{type:1,components:[{type:4,custom_id:"amount",style:1,label:l==="ja"?"防衛ポイント":"Defence points",placeholder:"1000",required:true,min_length:1,max_length:8}]}]}});
 }
 if(i.type===5&&/^def_sendamount_\d+_(en|ja)$/.test(cid)){
   const a=cid.split("_"),rid=Number(a[2]),l=a[3]==="ja"?"ja":"en",n=Number(i.data.components?.[0]?.components?.[0]?.value||""),token=i.token,appId=i.application_id;
   if(!Number.isInteger(n)||n<=0||n>99999999)return dReply(l==="ja"?"❌ 1以上の整数を入力してください。":"❌ Enter a whole number greater than 0.");
   ctx.waitUntil((async()=>{try{
     const loaded=await ghJson(env,DISCORD_PLAYERS_PATH),p=(loaded.data||{})[id];
     let content,components=[];
     if(!p?.travian_uid) content=l==="ja"?"❌ まず **/def** で登録してください。":"❌ Please register first with **/def**.";
     else {
       const rs=await loadActiveRequests(env),q=(rs||[]).find(x=>Number(x.id)===rid)||null;
       if(!q) content=l==="ja"?"❌ 防衛要請を読み込めませんでした。":"❌ Could not load the defence request.";
       else {
         const remaining=Math.max(0,Number(q.required_def||0)-Number(q.collected_def||0));
         if(remaining<=0) content=l==="ja"?"✅ この防衛要請は既に完了しています。":"✅ This defence request is already covered.";
         else {const amount=Math.min(n,remaining);content=sendSourceText(p,q,l)+"\n\n🛡 **"+amount+"**";components=sendSourceButtons(p,q,l).map(row=>({type:1,components:row.components.map(b=>({...b,custom_id:b.custom_id+"_a"+amount}))}));}
       }
     }
     await fetch("https://discord.com/api/v10/webhooks/"+appId+"/"+token+"/messages/@original",{method:"PATCH",headers:{"content-type":"application/json"},body:JSON.stringify({content,components})});
   }catch(e){console.error("Fast-path amount handling failed:",e);}})());
   return Response.json({type:5,data:{flags:64}});
 }
 if(i.type===3&&(/^def_src_(\d+)_(\d+)_(\d+)_(en|ja)_a(\d+)$/.test(cid)||/^def_srcskip_(\d+)_(en|ja)_a(\d+)$/.test(cid))){
   const withVillage=cid.startsWith("def_src_")&&!cid.startsWith("def_srcskip_");
   const m=withVillage?cid.match(/^def_src_(\d+)_(\d+)_(\d+)_(en|ja)_a(\d+)$/):cid.match(/^def_srcskip_(\d+)_(en|ja)_a(\d+)$/);
   const rid=+m[1],idx=withVillage?+m[2]:null,routeIdx=withVillage?+m[3]:0,l=withVillage?m[4]:m[2],n=+(withVillage?m[5]:m[3]),token=i.token,appId=i.application_id;
   ctx.waitUntil((async()=>{try{
     const loaded=await ghJson(env,DISCORD_PLAYERS_PATH),p=(loaded.data||{})[id];
     let content;
     if(!p?.travian_uid) content=l==="ja"?"❌ まず **/def** で登録してください。":"❌ Please register first with **/def**.";
     else {
       const res=await saveDiscordPledge(env,p,id,rid,l,n,idx,routeIdx);
       if(res.error) content=res.error;
       else if(withVillage){const leg=res.plan[0];content=(l==="ja"?"✅ **防衛を登録しました**":"✅ **Defence added**")+"\n\n🛡 **"+res.amount+"**\n🏘 **"+String(leg.village).replace(" ","|")+"**\n🚨 "+(l==="ja"?"送信期限":"Send by")+": **"+leg.deadline+"**\n🎯 **"+res.q.target_x+"|"+res.q.target_y+"**\n📊 "+res.q.collected_def+" / "+res.q.required_def;}
       else content=(l==="ja"?"✅ **防衛を登録しました**":"✅ **Defence added**")+"\n\n🛡 **"+res.amount+"**\n⏱ "+(l==="ja"?"村を選択していないため、送信時刻は計算されません。":"No village selected — departure time was not calculated.")+"\n🎯 **"+res.q.target_x+"|"+res.q.target_y+"**\n📊 "+res.q.collected_def+" / "+res.q.required_def;
     }
     await fetch("https://discord.com/api/v10/webhooks/"+appId+"/"+token+"/messages/@original",{method:"PATCH",headers:{"content-type":"application/json"},body:JSON.stringify({content,components:[]})});
   }catch(e){console.error("Fast-path pledge failed:",e);}})());
   return Response.json({type:5,data:{flags:64}});
 }

 try{
  const loaded=await ghJson(env,DISCORD_PLAYERS_PATH),players=loaded.data||{},p=players[id];
  if(i.type===2&&i.data?.name==="def"){
   if(p?.travian_uid){
     // The profile is already loaded at this point. Acknowledge /def immediately,
     // then build the personal centre (including active requests) in background.
     const l=p.language==="ja"?"ja":"en",token=i.token,appId=i.application_id;
     ctx.waitUntil((async()=>{try{
       const cd=await centreData(env,p);
       await fetch("https://discord.com/api/v10/webhooks/"+appId+"/"+token+"/messages/@original",{
         method:"PATCH",headers:{"content-type":"application/json"},
         body:JSON.stringify({content:cd.text,components:personalCentreComponents(cd.requests,cd.lang,canCreateDefence(i),id),flags:64})
       });
       await refreshDiscordCentre(env);
     }catch(e){console.error("Deferred /def centre failed:",e);}})());
     return Response.json({type:5,data:{flags:64}});
   }
   return dReply("🛡 **WORLD Defence**\n\n🇬🇧 "+DTXT.en.choose+"\n🇯🇵 "+DTXT.ja.choose,langButtons());
  }
  
  
  if(i.type===3&&/^def_public_send_\d+$/.test(i.data?.custom_id||"")){
   if(!p?.travian_uid)return dReply("❌ Please register first with **/def**.\n❌ まず **/def** で登録してください。");
   const rid=Number(i.data.custom_id.split("_")[3]),l=p.language==="ja"?"ja":"en";
   return Response.json({type:9,data:{custom_id:"def_sendamount_"+rid+"_"+l,title:l==="ja"?"防衛兵を送る":"Send Defence",components:[{type:1,components:[{type:4,custom_id:"amount",style:1,label:l==="ja"?"防衛ポイント":"Defence points",placeholder:"1000",required:true,min_length:1,max_length:8}]}]}});
  }
  if(i.type===3&&/^def_send_\d+_(en|ja)$/.test(i.data?.custom_id||"")){
   const a=i.data.custom_id.split("_"),rid=Number(a[2]),l=a[3]==="ja"?"ja":"en";
   return Response.json({type:9,data:{custom_id:"def_sendamount_"+rid+"_"+l,title:l==="ja"?"防衛兵を送る":"Send Defence",components:[{type:1,components:[{type:4,custom_id:"amount",style:1,label:l==="ja"?"防衛ポイント":"Defence points",placeholder:"1000",required:true,min_length:1,max_length:8}]}]}});
  }
  if(i.type===5&&/^def_sendamount_\d+_(en|ja)$/.test(i.data?.custom_id||"")){
   const a=i.data.custom_id.split("_"),rid=Number(a[2]),l=a[3]==="ja"?"ja":"en",n=Number(i.data.components?.[0]?.components?.[0]?.value||"");
   if(!Number.isInteger(n)||n<=0||n>99999999)return dReply(l==="ja"?"❌ 1以上の整数を入力してください。":"❌ Enter a whole number greater than 0.");
   // Modal submit must be acknowledged before any GitHub request. Build the
   // village choice asynchronously and edit the deferred ephemeral response.
   const token=i.token,appId=i.application_id;
   ctx.waitUntil((async()=>{try{
     const rs=await loadActiveRequests(env),q=(rs||[]).find(x=>Number(x.id)===rid)||null;
     let content,components=[];
     if(!q){
       content=l==="ja"?"❌ 防衛要請を読み込めませんでした。もう一度ボタンを押してください。":"❌ Could not load the defence request. Please press Send Defence again.";
     }else{
       const remaining=Math.max(0,Number(q.required_def||0)-Number(q.collected_def||0));
       if(remaining<=0) content=l==="ja"?"✅ この防衛要請は既に完了しています。":"✅ This defence request is already covered.";
       else{
         const amount=Math.min(n,remaining);
         content=sendSourceText(p,q,l)+"\n\n🛡 **"+amount+"**";
         components=sendSourceButtons(p,q,l).map(row=>({type:1,components:row.components.map(b=>({...b,custom_id:b.custom_id+"_a"+amount}))}));
       }
     }
     await fetch("https://discord.com/api/v10/webhooks/"+appId+"/"+token+"/messages/@original",{method:"PATCH",headers:{"content-type":"application/json"},body:JSON.stringify({content,components})});
   }catch(e){
     console.error("Deferred Discord amount handling failed:",e);
     try{await fetch("https://discord.com/api/v10/webhooks/"+appId+"/"+token+"/messages/@original",{method:"PATCH",headers:{"content-type":"application/json"},body:JSON.stringify({content:l==="ja"?"❌ 防衛要請を読み込めませんでした。もう一度お試しください。":"❌ Could not load the defence request. Please try again.",components:[]})});}catch(_){}
   }})());
   return Response.json({type:5,data:{flags:64}});
  }
    if(i.type===3&&/^def_src_(\d+)_(\d+)_(en|ja)_a(\d+)$/.test(i.data?.custom_id||"")){
   const m=i.data.custom_id.match(/^def_src_(\d+)_(\d+)_(en|ja)_a(\d+)$/),rid=+m[1],idx=+m[2],l=m[3],n=+m[4],token=i.token,appId=i.application_id;
   ctx.waitUntil((async()=>{try{
     const res=await saveDiscordPledge(env,p,id,rid,l,n,idx);
     let content;
     if(res.error) content=res.error;
     else {const leg=res.plan[0];content=(l==="ja"?"✅ **防衛を登録しました**":"✅ **Defence added**")+"\n\n🛡 **"+res.amount+"**\n🏘 **"+String(leg.village).replace(" ","|")+"**\n🚨 "+(l==="ja"?"送信期限":"Send by")+": **"+leg.deadline+"**\n🎯 **"+res.q.target_x+"|"+res.q.target_y+"**\n📊 "+res.q.collected_def+" / "+res.q.required_def;}
     await fetch("https://discord.com/api/v10/webhooks/"+appId+"/"+token+"/messages/@original",{method:"PATCH",headers:{"content-type":"application/json"},body:JSON.stringify({content,components:[]})});
   }catch(e){console.error("Deferred Discord village pledge failed:",e);}})());
   return Response.json({type:5,data:{flags:64}});
  }
  if(i.type===3&&/^def_srcskip_(\d+)_(en|ja)_a(\d+)$/.test(i.data?.custom_id||"")){
   // Acknowledge immediately; GitHub save + centre refresh continue in background.
   const m=i.data.custom_id.match(/^def_srcskip_(\d+)_(en|ja)_a(\d+)$/),rid=+m[1],l=m[2],n=+m[3],token=i.token,appId=i.application_id;
   ctx.waitUntil((async()=>{try{
     const res=await saveDiscordPledge(env,p,id,rid,l,n,null);
     const content=res.error||((l==="ja"?"✅ **防衛を登録しました**":"✅ **Defence added**")+"\n\n🛡 **"+res.amount+"**\n⏱ "+(l==="ja"?"村を選択していないため、送信時刻は計算されません。":"No village selected — departure time was not calculated.")+"\n🎯 **"+res.q.target_x+"|"+res.q.target_y+"**\n📊 "+res.q.collected_def+" / "+res.q.required_def);
     await fetch("https://discord.com/api/v10/webhooks/"+appId+"/"+token+"/messages/@original",{method:"PATCH",headers:{"content-type":"application/json"},body:JSON.stringify({content,components:[]})});
   }catch(e){console.error("Deferred Discord pledge failed:",e);}})());
   return Response.json({type:5,data:{flags:64}});
  }

  if(i.type===3&&/^def_hero_(en|ja)$/.test(i.data?.custom_id||"")){const l=i.data.custom_id.endsWith("_ja")?"ja":"en",inv=heroInventory(p),hi=(p.villages||[]).findIndex(v=>v.hero?.present),txt=(l==="ja"?"🦸 **英雄と装備**":"🦸 **Hero & gear**")+"\n\n"+(l==="ja"?"英雄の村: ":"Hero village: ")+(hi>=0?String(p.villages[hi].coordinates).replace(" ","|"):"—")+"\n🚩 "+(inv.standards.join("%, ")||"—")+(inv.standards.length?"%":"")+"\n🥾 "+(inv.boots.join("%, ")||"—")+(inv.boots.length?"%":"")+"\n🗺 "+(inv.maps.join("%, ")||"—")+(inv.maps.length?"%":"");const rows=(p.villages||[]).slice(0,4).map((v,n)=>({type:1,components:[{type:2,style:v.hero?.present?3:2,custom_id:"def_heroloc_"+n+"_"+l,label:"🦸 "+String(v.coordinates).replace(" ","|")}]}));rows.push({type:1,components:[{type:2,style:1,custom_id:"def_gear_standards_"+l,label:"🚩 Standards"},{type:2,style:1,custom_id:"def_gear_boots_"+l,label:"🥾 Boots"},{type:2,style:1,custom_id:"def_gear_maps_"+l,label:"🗺 Maps"}]});return dReply(txt,rows);}
  if(i.type===3&&/^def_heroloc_(\d+)_(en|ja)$/.test(i.data?.custom_id||"")){const a=i.data.custom_id.split("_"),idx=+a[2],l=a[3];for(const v of p.villages||[])v.hero={...(v.hero||{}),present:false};if(p.villages?.[idx])p.villages[idx].hero={...(p.villages[idx].hero||{}),present:true};p.language=l;players[id]=p;await ghSave(env,DISCORD_PLAYERS_PATH,players,loaded.sha,"Update WORLD Discord hero location");return dReply(l==="ja"?"✅ 英雄の村を保存しました。":"✅ Hero village saved.",settingsButtons(l));}
  if(i.type===3&&/^def_gear_(standards|boots|maps)_(en|ja)$/.test(i.data?.custom_id||"")){const m=i.data.custom_id.match(/^def_gear_(standards|boots|maps)_(en|ja)$/),kind=m[1],l=m[2];return Response.json({type:9,data:{custom_id:"def_gearval_"+kind+"_"+l,title:(kind==="standards"?"Standards":kind==="boots"?"Boots":"Maps"),components:[{type:1,components:[{type:4,custom_id:"values",style:1,label:l==="ja"?"所持ボーナス (%)":"Owned bonuses (%)",placeholder:"10, 15, 20",required:false,max_length:60}]}]}});}
  if(i.type===5&&/^def_gearval_(standards|boots|maps)_(en|ja)$/.test(i.data?.custom_id||"")){const m=i.data.custom_id.match(/^def_gearval_(standards|boots|maps)_(en|ja)$/),kind=m[1],l=m[2],raw=String(i.data.components?.[0]?.components?.[0]?.value||"").trim();let vals=[];if(raw){vals=raw.split(/[ ,;]+/).filter(Boolean).map(Number);if(vals.some(x=>!Number.isInteger(x)||x<=0||x>100))return dReply(l==="ja"?"❌ 1〜100の割合を入力してください。":"❌ Enter percentage values from 1 to 100.");vals=[...new Set(vals)].sort((a,b)=>a-b);}p.hero_inventory=p.hero_inventory||{standards:[],boots:[],maps:[]};p.hero_inventory[kind]=vals;p.language=l;players[id]=p;await ghSave(env,DISCORD_PLAYERS_PATH,players,loaded.sha,"Update WORLD Discord hero inventory");return dReply("✅ "+DTXT[l].saved,settingsButtons(l));}

  if(i.type===3&&i.data?.custom_id==="def_language")return dReply("🌐 🇬🇧 "+DTXT.en.choose+"\n🇯🇵 "+DTXT.ja.choose,langButtons());
  if(i.type===3&&/^def_add_(en|ja)$/.test(i.data?.custom_id||"")){
   const l=i.data.custom_id.endsWith("_ja")?"ja":"en",t=DTXT[l];
   return Response.json({type:9,data:{custom_id:"def_addcoords_"+l,title:t.addVillage,components:[{type:1,components:[{type:4,custom_id:"coords",style:1,label:t.coord,placeholder:t.hint,required:true,min_length:3,max_length:9}]}]}});
  }
  if(i.type===5&&/^def_addcoords_(en|ja)$/.test(i.data?.custom_id||"")){
   const l=i.data.custom_id.endsWith("_ja")?"ja":"en",t=DTXT[l],rawc=i.data.components?.[0]?.components?.[0]?.value||"",m=String(rawc).trim().match(/^(-?\d{1,3})\s+(-?\d{1,3})$/);
   if(!m)return dReply(t.bad);const x=+m[1],y=+m[2];if(x< -200||x>200||y< -200||y>200)return dReply(t.bad);
   const map=await getMap(),v=mapVillage(map,x,y);if(!v)return dReply(t.miss);if(v.aid!==WORLD_ALLIANCE_ID)return dReply(t.world);if(Number(v.uid)!==Number(p.travian_uid))return dReply(t.notYours);
   if(!(p.villages||[]).some(z=>z.coordinates===x+" "+y))p.villages.push({coordinates:x+" "+y,name:v.name,arena:0,troops:{},hero:{present:false}});
   p.language=l;players[id]=p;await ghSave(env,DISCORD_PLAYERS_PATH,players,loaded.sha,"Add WORLD Discord village "+v.name);
   return dReply("✅ "+t.saved+"\n\n🏘 **"+v.name+"** ("+x+"|"+y+")",settingsButtons(l));
  }
  if(i.type===3&&/^def_troops_(en|ja)$/.test(i.data?.custom_id||"")){const l=i.data.custom_id.endsWith("_ja")?"ja":"en";return dReply("🛡 **"+DTXT[l].troops+"**",villageButtons(p,l));}
  if(i.type===3&&/^def_village_(\d+)_(en|ja)$/.test(i.data?.custom_id||"")){const a=i.data.custom_id.split("_"),idx=+a[2],l=a[3]==="ja"?"ja":"en";return dReply("🏘 **"+(p.villages?.[idx]?.name||"Village")+"**\n🛡 "+DTXT[l].troops+"\n🏟 "+DTXT[l].arena+": "+Number(p.villages?.[idx]?.arena||0),unitButtons(p,idx,l).concat([{type:1,components:[{type:2,style:2,custom_id:"def_arena_"+idx+"_"+l,label:"🏟 "+DTXT[l].arena+" — "+Number(p.villages?.[idx]?.arena||0)}]}]));}
  if(i.type===3&&/^def_unit_(\d+)_[a-z_]+_(en|ja)$/.test(i.data?.custom_id||"")){const a=i.data.custom_id.split("_"),idx=+a[2],l=a[a.length-1],unit=a.slice(3,-1).join("_"),u=(DEF_UNITS[p.race]||[]).find(z=>z[0]===unit),label=l==="ja"?(u?.[2]||unit):(u?.[1]||unit);return Response.json({type:9,data:{custom_id:"def_amount_"+idx+"_"+unit+"_"+l,title:label,components:[{type:1,components:[{type:4,custom_id:"amount",style:1,label:l==="ja"?"兵士数":"Troop amount",placeholder:"0",required:true,min_length:1,max_length:8}]}]}});}
  if(i.type===5&&/^def_amount_(\d+)_[a-z_]+_(en|ja)$/.test(i.data?.custom_id||"")){const a=i.data.custom_id.split("_"),idx=+a[2],l=a[a.length-1],unit=a.slice(3,-1).join("_"),rawa=i.data.components?.[0]?.components?.[0]?.value||"",n=Number(rawa);if(!Number.isInteger(n)||n<0||n>99999999)return dReply(l==="ja"?"❌ 0以上の整数を入力してください。":"❌ Enter a whole number of 0 or more.");p.villages[idx].troops[unit]=n;p.language=l;players[id]=p;await ghSave(env,DISCORD_PLAYERS_PATH,players,loaded.sha,"Update WORLD Discord troops");return dReply("✅ "+DTXT[l].saved+"\n\n🛡 "+n,unitButtons(p,idx,l));}
  if(i.type===3&&/^def_arena_(\d+)_(en|ja)$/.test(i.data?.custom_id||"")){const a=i.data.custom_id.split("_"),idx=+a[2],l=a[3];return Response.json({type:9,data:{custom_id:"def_arenaval_"+idx+"_"+l,title:DTXT[l].arena,components:[{type:1,components:[{type:4,custom_id:"arena",style:1,label:l==="ja"?"闘技場レベル (0-20)":"Tournament Square level (0-20)",placeholder:"0",required:true,min_length:1,max_length:2}]}]}});}
  if(i.type===5&&/^def_arenaval_(\d+)_(en|ja)$/.test(i.data?.custom_id||"")){const a=i.data.custom_id.split("_"),idx=+a[2],l=a[3],n=Number(i.data.components?.[0]?.components?.[0]?.value||"");if(!Number.isInteger(n)||n<0||n>20)return dReply(l==="ja"?"❌ 0〜20を入力してください。":"❌ Enter a level from 0 to 20.");p.villages[idx].arena=n;p.language=l;players[id]=p;await ghSave(env,DISCORD_PLAYERS_PATH,players,loaded.sha,"Update WORLD Discord arena");return dReply("✅ "+DTXT[l].saved+"\n\n🏟 "+DTXT[l].arena+": "+n,unitButtons(p,idx,l));}

  if(i.type===3&&/^def_lang_(en|ja)$/.test(i.data?.custom_id||"")){const l=i.data.custom_id.endsWith("_ja")?"ja":"en";if(p?.travian_uid){p.language=l;players[id]=p;await ghSave(env,DISCORD_PLAYERS_PATH,players,loaded.sha,"Update WORLD Discord language");const cd=await centreData(env,p);return dReply("✅ "+DTXT[l].saved+"\n\n"+cd.text,personalCentreComponents(cd.requests,l,canCreateDefence(i),id));}return dReply("🛡 **WORLD Defence**\n\n"+DTXT[l].wait,regButton(l));}
  if(i.type===3&&/^def_register_(en|ja)$/.test(i.data?.custom_id||"")){
   const l=i.data.custom_id.endsWith("_ja")?"ja":"en",t=DTXT[l];
   return Response.json({type:9,data:{custom_id:"def_coords_"+l,title:t.title,components:[{type:1,components:[{type:4,custom_id:"coords",style:1,label:t.coord,placeholder:t.hint,required:true,min_length:3,max_length:9}]}]}});
  }
  if(i.type===5&&/^def_coords_(en|ja)$/.test(i.data?.custom_id||"")){
   const l=i.data.custom_id.endsWith("_ja")?"ja":"en",t=DTXT[l],rawc=i.data.components?.[0]?.components?.[0]?.value||"",m=String(rawc).trim().match(/^(-?\d{1,3})\s+(-?\d{1,3})$/);
   if(!m)return dReply(t.bad);const x=+m[1],y=+m[2];if(x< -200||x>200||y< -200||y>200)return dReply(t.bad);
   const map=await getMap(),v=mapVillage(map,x,y);if(!v)return dReply(t.miss);if(v.aid!==WORLD_ALLIANCE_ID)return dReply(t.world);if(await uidUsed(env,v.uid,players,id,map))return dReply(t.dup);
   players[id]={discord_id:id,discord_username:i.member?.user?.username||"",discord_global_name:i.member?.user?.global_name||"",language:l,travian_uid:v.uid,player_name:v.player,race:({1:"roman",2:"teuton",3:"gaul",6:"egyptian",7:"hun",8:"spartan"})[v.tribe]||null,tribe:v.tribe,villages:[{coordinates:x+" "+y,name:v.name,arena:0,troops:{},hero:{present:false}}],hero_inventory:{standards:[],boots:[],maps:[]},state:null};
   await ghSave(env,DISCORD_PLAYERS_PATH,players,loaded.sha,"Register WORLD Discord player "+v.player);
   return dReply(t.done+"\n\n👤 **"+t.account+":** "+v.player+"\n🏘 **"+t.village+":** "+v.name+" ("+x+"|"+y+")\n⚔️ **"+t.tribe+":** "+tribeName(v.tribe,l));
  }
  if(p){const cd=await centreData(env,p);return dReply(cd.text,personalCentreComponents(cd.requests,cd.lang,canCreateDefence(i),id));}return dReply("Use /def.");
 }catch(e){console.error("Discord Defence error:",e);const l=i.data?.custom_id?.endsWith("_ja")?"ja":"en";return dReply(l==="ja"?"❌ 内部エラーが発生しました。もう一度お試しください。":"❌ Internal error. Please try again.");}
}

const MAX_QUEUE_DELAY_SECONDS = 86400;

function serverNowText() {
  const d=new Date(),pad=n=>String(n).padStart(2,"0");
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth()+1)}-${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`;
}
function secondsUntilServer(localText) {
  return Math.floor((parseServerTime(String(localText||""))-Date.now())/1000);
}

async function queueReminder(env, payload) {
  const delay = secondsUntilServer(payload.reminder_at);
  if (!Number.isFinite(delay)) throw new Error("Invalid reminder_at");
  if (delay <= 0) {
    await env.DEFENCE_REMINDERS.send(payload, { delaySeconds: 0 });
  } else {
    await env.DEFENCE_REMINDERS.send(payload, {
      delaySeconds: Math.min(delay, MAX_QUEUE_DELAY_SECONDS)
    });
  }
}

async function queueDiscordExpiry(env, requestItem) {
  const attackAt = String(requestItem.attack_time || "");
  const attackMs = parseServerTime(attackAt);
  if (!Number.isFinite(attackMs)) return;
  await queueReminder(env, {
    kind: "discord_request_expiry",
    request_id: Number(requestItem.id),
    reminder_at: formatServerTime(attackMs + 90 * 1000)
  });
}

async function handleDiscordExpiry(env, item) {
  const rq = await ghJson(env, "data/defence/requests.json");
  const list = Array.isArray(rq.data) ? rq.data : [];
  const q = list.find(x => Number(x.id) === Number(item.request_id));
  if (!q) return;
  const remaining = secondsUntilServer(q.attack_time);
  if (Number.isFinite(remaining) && remaining > 0) {
    item.reminder_at = formatServerTime(parseServerTime(q.attack_time) + 90 * 1000);
    await queueReminder(env, item);
    return;
  }
  await refreshDiscordCentre(env);
}

async function sendDiscordReminder(env,item){
  const l=item.language==="ja"?"ja":"en";
  const dm=await discordApi(env,"/users/@me/channels","POST",{recipient_id:String(item.discord_id)});
  const coords=String(item.village||"?").replace(" ","|");
  const target=String(item.target_x)+"|"+String(item.target_y);
  const text=l==="ja"
    ? "🚨 **防衛兵を送る時間です**\n\n🏘 **"+coords+"** → 🎯 **"+target+"**\n🛡 **"+Number(item.def_points||0).toLocaleString()+"** 防衛ポイント\n⚡ "+(item.gear_label||"No hero")+"\n\n🚨 **送信期限: "+(item.deadline||"?")+"**\n⚔️ 攻撃: **"+(item.attack_time_display||item.attack_time||"?")+"**\n\n⏱ 送信期限まで約5分です。"
    : "🚨 **TIME TO SEND DEFENCE**\n\n🏘 **"+coords+"** → 🎯 **"+target+"**\n🛡 **"+Number(item.def_points||0).toLocaleString()+"** defence points\n⚡ "+(item.gear_label||"No hero")+"\n\n🚨 **SEND BY: "+(item.deadline||"?")+"**\n⚔️ Attack: **"+(item.attack_time_display||item.attack_time||"?")+"**\n\n⏱ About 5 minutes remain to send.";
  await discordApi(env,"/channels/"+dm.id+"/messages","POST",{content:text,allowed_mentions:{parse:[]}});
}

async function sendPrivateReminder(env, item) {
  const mode = item.speed_mode === "hero" ? "🦸 С героем"
    : item.speed_mode === "ram" ? "🐏 + 1 таран"
    : item.speed_mode === "catapult" ? "🪨 + 1 катапульта"
    : "⚡ Без героя";
  const warning = item.speed_mode === "ram"
    ? "\n\n❗ Не забудь добавить <b>1 таран</b>."
    : item.speed_mode === "catapult"
      ? "\n\n❗ Не забудь добавить <b>1 катапульту</b>." : "";
  // Travian officially supports opening Rally Point with x/y directly.
  // Using coordinates avoids targetMapId conversion mistakes (especially Y sign).
  const tx = Number(item.target_x);
  const ty = Number(item.target_y);
  const sendDefUrl =
    `https://ts8.x1.asia.travian.com/build.php?id=39&tt=2&x=${encodeURIComponent(tx)}&y=${encodeURIComponent(ty)}`;

  const text =
    "<b>🚨 ПОРА ОТПРАВЛЯТЬ ДЕФ</b>\n\n" +
    `🏘 <b>${item.village || "?"}</b> → 🎯 <b>${item.target_x} ${item.target_y}</b>\n` +
    `🛡 <b>${item.def_points || 0}</b> очков\n` +
    `${mode}\n\n` +
    `🚨 Отправить до: <b>${item.deadline || "?"}</b>\n` +
    `⚔️ Атака: <b>${item.attack_time_display || item.attack_time || "?"}</b>\n\n` +
    "⏱ До отправки около 5 минут." +
    warning;

  const response = await fetch(
    `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: item.private_chat_id,
        text,
        parse_mode: "HTML",
        reply_markup: {
          inline_keyboard: [[
            { text: "⚔️ Отправить деф", url: sendDefUrl }
          ]]
        }
      })
    }
  );
  if (!response.ok) throw new Error(`Telegram reminder ${response.status}: ${await response.text()}`);
}


async function sendTelegram(env, chatId, text) {
  const response = await fetch(
    `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: chatId,
        message_thread_id: THREAD_ID,
        text,
        parse_mode: "HTML"
      })
    }
  );

  if (!response.ok) {
    throw new Error(`Telegram sendMessage ${response.status}: ${await response.text()}`);
  }
}

async function answerCallback(env, callbackQueryId) {
  const response = await fetch(
    `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/answerCallbackQuery`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ callback_query_id: callbackQueryId })
    }
  );

  if (!response.ok) {
    console.error(`Telegram answerCallbackQuery ${response.status}: ${await response.text()}`);
  }
}

async function loadActiveRequests(env) {
  const url = `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/contents/data/defence/requests.json?ref=${GITHUB_REF}`;
  const response = await fetch(url, {
    headers: {
      "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
      "Accept": "application/vnd.github+json",
      "User-Agent": "travian-defence"
    }
  });
  if (!response.ok) {
    throw new Error(`GitHub requests.json ${response.status}: ${await response.text()}`);
  }

  const payload = await response.json();
  const raw = atob(String(payload.content || "").replace(/\s/g, ""));
  const requests = JSON.parse(raw);
  if (!Array.isArray(requests)) return [];

  // Travian Asia server time is UTC. Do not use Europe/London here:
  // during British Summer Time London is UTC+1 and requests disappear
  // from Discord one hour too early.
  const d = new Date();
  const pad = n => String(n).padStart(2, "0");
  const nowText = `${d.getUTCFullYear()}-${pad(d.getUTCMonth()+1)}-${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`;

  return requests.filter(req =>
    req && req.status === "active" &&
    Number(req.required_def || 0) > Number(req.collected_def || 0) &&
    String(req.attack_time || "") > nowText
  );
}

async function sendStartMenu(env, message) {
  const url = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`;

  let requests = [];
  try {
    requests = await loadActiveRequests(env);
  } catch (error) {
    console.error("Failed to load active defence requests:", error);
  }

  const lines = ["<b>🛡 ЦЕНТР ДЕФА</b>", ""];
  if (requests.length) {
    lines.push("<b>Активные заявки:</b>", "");
    for (const req of requests) {
      const collected = Number(req.collected_def || 0);
      const required = Number(req.required_def || 0);
      lines.push(
        `🟢 <b>#${req.id}</b> — ${req.target_x}|${req.target_y}`,
        `⚔️ Атака: <b>${req.attack_time_display || req.attack_time}</b>`,
        `🛡 Деф: <b>${collected}</b> / <b>${required}</b> очков`,
        ""
      );
    }
  } else {
    lines.push("Активных заявок сейчас нет.", "");
  }

  lines.push(
    "Деф должен прибыть <b>ДО</b> времени атаки.",
    "",
    "Выберите действие:"
  );

  const body = {
    chat_id: message.chat.id,
    message_thread_id: THREAD_ID,
    text: lines.join("\n"),
    parse_mode: "HTML",
    reply_markup: {
      inline_keyboard: [
        [{ text: "➕ Запросить деф", callback_data: "request_def" }],
        [{ text: "🛡 Отправить деф", callback_data: "send_def" }],
        [{ text: "⚙️ Мои настройки", callback_data: "settings" }]
      ]
    }
  };

  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });

  if (!response.ok) {
    throw new Error(`Telegram sendMessage ${response.status}: ${await response.text()}`);
  }
}

async function switchTelegramToPolling(env) {
  if (!env.TELEGRAM_BOT_TOKEN) throw new Error("Cloudflare: не задан TELEGRAM_BOT_TOKEN");
  const response = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/deleteWebhook`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ drop_pending_updates: false })
  });
  const body = await response.text();
  if (!response.ok) throw new Error(`Telegram deleteWebhook ${response.status}: ${body.slice(0, 1000)}`);
  try {
    const parsed = JSON.parse(body);
    if (!parsed.ok) throw new Error(`Telegram deleteWebhook failed: ${body.slice(0, 1000)}`);
  } catch (error) {
    if (error instanceof SyntaxError) throw new Error(`Telegram deleteWebhook invalid response: ${body.slice(0, 1000)}`);
    throw error;
  }
}

async function restoreTelegramWebhook(env) {
  if (!env.TELEGRAM_BOT_TOKEN) throw new Error("Cloudflare: не задан TELEGRAM_BOT_TOKEN");
  const response = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/setWebhook`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      url: "https://travian-defence.dmrylezfree.workers.dev/",
      allowed_updates: ["message", "callback_query"]
    })
  });
  const body = await response.text();
  if (!response.ok) throw new Error(`Telegram setWebhook ${response.status}: ${body.slice(0, 1000)}`);
  const parsed = JSON.parse(body);
  if (!parsed.ok) throw new Error(`Telegram setWebhook failed: ${body.slice(0, 1000)}`);
}

async function dispatch(env, update = null, workflow = GITHUB_WORKFLOW) {
  if (!env.GITHUB_TOKEN) {
    throw new Error("Cloudflare: не задан GITHUB_TOKEN");
  }
  if (!env.TELEGRAM_BOT_TOKEN) {
    throw new Error("Cloudflare: не задан TELEGRAM_BOT_TOKEN");
  }

  // Close the webhook before dispatching GitHub. This prevents a second
  // Telegram update from starting another workflow while the first runner
  // is still booting and has not reached defence_poll.py yet.
  if (update) {
    await switchTelegramToPolling(env);
  }

  const url =
    `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/actions/workflows/${workflow}/dispatches`;

  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
      "Accept": "application/vnd.github+json",
      "Content-Type": "application/json",
      "User-Agent": "travian-defence"
    },
    body: JSON.stringify({
      ref: GITHUB_REF,
      inputs: {
        action: update?.callback_query ? "callback" : "message",
        thread_id: String(THREAD_ID),
        update_json: update ? JSON.stringify(update) : ""
      }
    })
  });

  if (!response.ok) {
    const details = await response.text();
    if (update) {
      try {
        await restoreTelegramWebhook(env);
      } catch (restoreError) {
        console.error("Failed to restore Telegram webhook after GitHub dispatch failure:", restoreError);
      }
    }
    throw new Error(`GitHub API ${response.status}: ${details.slice(0, 1500)}`);
  }
}

async function dispatchDiscordSync(env) {
  const url = `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/actions/workflows/${GITHUB_WORKFLOW}/dispatches`;
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
      "Accept": "application/vnd.github+json",
      "Content-Type": "application/json",
      "User-Agent": "travian-defence"
    },
    body: JSON.stringify({
      ref: GITHUB_REF,
      inputs: { action: "discord_sync", thread_id: String(THREAD_ID), update_json: "" }
    })
  });
  if (!response.ok) throw new Error(`Discord sync dispatch ${response.status}: ${await response.text()}`);
}

function getUpdateThreadId(update) {
  const message = update?.message || update?.edited_message;
  if (message) return Number(message.message_thread_id);
  const callback = update?.callback_query;
  if (callback?.message) return Number(callback.message.message_thread_id);
  return null;
}

function isDefCommand(message) {
  if (!message) return false;
  if (Number(message.message_thread_id) !== THREAD_ID) return false;

  const text = String(message.text || "").trim();
  return /^\/def(?:@[^\s]+)?(?:\s|$)/i.test(text);
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    if (request.method === "POST" && url.pathname === "/discord") {
      return handleDiscord(request, env, ctx);
    }

    if (request.method === "POST" && url.pathname === "/discord/request-sync") {
      const auth = request.headers.get("Authorization") || "";
      if (auth !== `Bearer ${env.TELEGRAM_BOT_TOKEN}`) {
        return new Response("Unauthorized", { status: 401 });
      }
      try {
        const body = await request.json();
        const incoming = body?.request;
        if (!incoming) {
          return Response.json({ ok: false, error: "request is required" }, { status: 400 });
        }
        const allocateId = incoming.id == null;

        // Persist the Telegram-created request through GitHub's API from the
        // Worker. This avoids depending on a potentially hanging git pull/push
        // on the VPS before Discord can see the new request.
        let saved = false;
        let lastError = null;
        for (let attempt = 1; attempt <= 3 && !saved; attempt++) {
          try {
            const current = await ghJson(env, "data/defence/requests.json");
            const requests = Array.isArray(current.data) ? current.data : [];
            if (allocateId) {
              incoming.id = Math.max(0, ...requests.map(q => Number(q.id) || 0)) + 1;
            }
            const index = requests.findIndex(q => Number(q.id) === Number(incoming.id));
            if (index >= 0) requests[index] = { ...requests[index], ...incoming };
            else requests.push(incoming);
            requests.sort((a,b) => Number(a.id||0) - Number(b.id||0));
            await ghSave(env, "data/defence/requests.json", requests, current.sha, "Sync Telegram defence request");
            saved = true;
          } catch (error) {
            lastError = error;
            if (attempt < 3) await new Promise(resolve => setTimeout(resolve, 250 * attempt));
          }
        }
        if (!saved) throw lastError || new Error("Failed to persist Telegram defence request");

        ctx.waitUntil(
          refreshDiscordCentre(env).catch(error => {
            console.error("Discord request sync refresh failed:", error instanceof Error ? error.message : String(error));
          })
        );
        return Response.json({ ok: true, synced: Number(incoming.id), request: incoming });
      } catch (error) {
        console.error("Telegram request sync failed:", error instanceof Error ? error.message : String(error));
        return Response.json({ ok: false, error: String(error) }, { status: 500 });
      }
    }

    if (request.method === "POST" && url.pathname === "/discord/refresh") {
      const auth = request.headers.get("Authorization") || "";
      if (auth !== `Bearer ${env.TELEGRAM_BOT_TOKEN}`) {
        return new Response("Unauthorized", { status: 401 });
      }
      // A full Discord rebuild may need several API calls (threads, pins,
      // cards and role lookup). Acknowledge Telegram immediately and finish
      // the rebuild in the Worker's execution context.
      ctx.waitUntil(
        refreshDiscordCentre(env).catch(error => {
          console.error("Discord centre refresh failed:", error instanceof Error ? error.message : String(error));
        })
      );
      return Response.json({ ok: true, queued: true });
    }

    if (request.method === "POST" && url.pathname === "/schedule-reminders") {
      const auth = request.headers.get("Authorization") || "";
      if (auth !== `Bearer ${env.TELEGRAM_BOT_TOKEN}`) {
        return new Response("Unauthorized", { status: 401 });
      }
      try {
        const body = await request.json();
        const reminders = Array.isArray(body?.reminders) ? body.reminders : [];
        for (const reminder of reminders) await queueReminder(env, reminder);
        return Response.json({ ok: true, scheduled: reminders.length });
      } catch (error) {
        return Response.json({ ok: false, error: String(error) }, { status: 400 });
      }
    }

    if (request.method !== "POST") {
      return new Response("OK");
    }

    let update;
    try {
      update = await request.json();
    } catch {
      return new Response("OK");
    }

    const message = update.message;
    const callback = update.callback_query;

    const privateChat =
      message?.chat?.type === "private" ||
      callback?.message?.chat?.type === "private";

    if (privateChat) {
      try {
        // Start the same long-polling Defence Bot session used by the alliance
        // thread. The triggering private update is passed into the session;
        // after the workflow disables the webhook, subsequent private clicks
        // and messages are handled immediately by the already-running poller.
        if (callback?.id) {
          await answerCallback(env, callback.id);
        }
        await dispatch(env, update);
      } catch (error) {
        console.error(error instanceof Error ? error.message : String(error));
      }
      return new Response("OK");
    }

    if (getUpdateThreadId(update) !== THREAD_ID) {
      return new Response("OK");
    }

    // /def only starts the workflow. The Python bot owns the single
    // authoritative Defence Centre message, including status colours,
    // buttons and pinning. Do not create a temporary duplicate menu here.
    if (message && isDefCommand(message)) {
      try {
        await dispatch(env, update);
      } catch (error) {
        const details = error instanceof Error ? error.message : String(error);
        console.error(details);

        try {
          await sendTelegram(
            env,
            message.chat.id,
            `❌ <b>Не удалось запустить Defence Bot</b>\n\n<code>${details.slice(0, 2000)}</code>`
          );
        } catch (telegramError) {
          console.error(
            telegramError instanceof Error ? telegramError.message : String(telegramError)
          );
        }
      }
      return new Response("OK");
    }

    // When the 510-second polling window has ended, Telegram is back on this
    // webhook. Old inline keyboards must still work. Forward the exact update
    // into a new workflow run; otherwise the update would be consumed by the
    // webhook and never reach getUpdates.
    if (callback || message) {
      if (callback?.id) {
        await answerCallback(env, callback.id);
      }

      try {
        await dispatch(env, update);
      } catch (error) {
        console.error(error instanceof Error ? error.message : String(error));
      }
    }

    return new Response("OK");
  },

  async queue(batch, env) {
    for (const message of batch.messages) {
      try {
        const item = message.body || {};
        if (item.kind === "discord_request_expiry") {
          await handleDiscordExpiry(env, item);
          message.ack();
          continue;
        }
        const remaining = secondsUntilServer(item.reminder_at);
        if (Number.isFinite(remaining) && remaining > 2) {
          message.retry({ delaySeconds: Math.min(remaining, MAX_QUEUE_DELAY_SECONDS) });
          continue;
        }
        if(item.platform==="discord")await sendDiscordReminder(env,item);
        else await sendPrivateReminder(env, item);
        message.ack();
      } catch (error) {
        console.error("Defence reminder failed:", error instanceof Error ? error.message : String(error));
        message.retry({ delaySeconds: 60 });
      }
    }
  }
};
