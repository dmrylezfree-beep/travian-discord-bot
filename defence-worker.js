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
function ghDecode(s){const b=atob(String(s||"").replace(/\s/g,""));return new TextDecoder().decode(Uint8Array.from(b,x=>x.charCodeAt(0)));}
function ghEncode(s){const a=new TextEncoder().encode(s);let b="";for(let i=0;i<a.length;i+=32768)b+=String.fromCharCode(...a.subarray(i,i+32768));return btoa(b);}
async function ghJson(env,path){const u="https://api.github.com/repos/"+GITHUB_OWNER+"/"+GITHUB_REPO+"/contents/"+path+"?ref="+GITHUB_REF;const r=await fetch(u,{headers:{Authorization:"Bearer "+env.GITHUB_TOKEN,Accept:"application/vnd.github+json","User-Agent":"travian-defence"}});if(!r.ok)throw new Error("GitHub "+path+" "+r.status);const p=await r.json();return {data:JSON.parse(ghDecode(p.content)),sha:p.sha};}
async function ghSave(env,path,data,sha,msg){const u="https://api.github.com/repos/"+GITHUB_OWNER+"/"+GITHUB_REPO+"/contents/"+path;const r=await fetch(u,{method:"PUT",headers:{Authorization:"Bearer "+env.GITHUB_TOKEN,Accept:"application/vnd.github+json","Content-Type":"application/json","User-Agent":"travian-defence"},body:JSON.stringify({message:msg,content:ghEncode(JSON.stringify(data,null,2)+"\n"),sha,branch:GITHUB_REF})});if(!r.ok)throw new Error("GitHub save "+path+" "+r.status+": "+await r.text());}
function sqlFields(row){let o=[],v="",q=false;for(let i=0;i<row.length;i++){const ch=row[i];if(ch==="'"){if(q&&row[i+1]==="'"){v+="'";i++;}else q=!q;}else if(ch===","&&!q){o.push(v.trim());v="";}else v+=ch;}o.push(v.trim());return o;}
function mapVillage(text,x,y){const rows=text.match(/\([^;\n]*?\)(?=,|;|\s*$)/g)||[];for(const row of rows){const f=sqlFields(row.slice(1,-1));if(f.length>=10&&Number(f[1])===x&&Number(f[2])===y)return {uid:Number(f[6]),name:f[5],player:f[7],aid:Number(f[8])||0,tribe:Number(f[3])};}return null;}
async function getMap(){const r=await fetch(TRAVIAN_MAP_URL,{headers:{"User-Agent":"travian-defence"}});if(!r.ok)throw new Error("map.sql "+r.status);return r.text();}
function tribeName(n,l){const a=l==="ja"?{1:"ローマン",2:"チュートン",3:"ガウル",6:"エジプト",7:"フン",8:"スパルタ"}:{1:"Romans",2:"Teutons",3:"Gauls",6:"Egyptians",7:"Huns",8:"Spartans"};return a[n]||String(n);}
async function uidUsed(env,uid,dp,myId,map){for(const [id,p] of Object.entries(dp))if(id!==myId&&Number(p?.travian_uid)===uid)return true;const tp=(await ghJson(env,TELEGRAM_PLAYERS_PATH)).data||{};for(const p of Object.values(tp)){if(Number(p?.travian_uid)===uid)return true;for(const v of p?.villages||[]){const m=String(v.coordinates||"").match(/^\s*(-?\d+)\s+(-?\d+)\s*$/);if(m&&mapVillage(map,+m[1],+m[2])?.uid===uid)return true;}}return false;}
async function centreData(env,p){const l=p.language==="ja"?"ja":"en",t=DTXT[l];let rs=[];try{rs=await loadActiveRequests(env);}catch{}let a=["🛡 **WORLD Defence**","","👤 **"+t.account+":** "+p.player_name,"🏘 **"+t.village+":** "+(p.villages?.[0]?.coordinates||"—"),"⚔️ **"+t.tribe+":** "+tribeName(p.tribe,l),"","**"+t.active+":**"];if(!rs.length)a.push(t.none);for(const q of rs)a.push("🟢 **#"+q.id+"** — "+q.target_x+"|"+q.target_y+" — 🛡 "+Number(q.collected_def||0).toLocaleString()+"/"+Number(q.required_def||0).toLocaleString()+" — ⚔️ "+(q.attack_time_display||q.attack_time));return a.join("\n");}


const DEF_UNITS={
 roman:[["legionnaire","Legionnaire","レジョネア"],["praetorian","Praetorian","プレトリアン"],["equites_caesaris","Equites Caesaris","エクイーツ・カエザリス"]],
 teuton:[["spearman","Spearman","スピアマン"],["paladin","Paladin","パラディン"]],
 gaul:[["phalanx","Phalanx","ファランクス"],["druidrider","Druidrider","ドルイドライダー"],["haeduan","Haeduan","ヘジュアン"]]
};
function settingsButtons(l){const t=DTXT[l];return [{type:1,components:[{type:2,style:1,custom_id:"def_add_"+l,label:t.addVillage,emoji:{name:"🏘️"}},{type:2,style:1,custom_id:"def_troops_"+l,label:t.troops,emoji:{name:"🛡️"}}]},{type:1,components:[{type:2,style:2,custom_id:"def_language",label:t.changeLang,emoji:{name:"🌐"}}]}];}
function villageButtons(p,l){return (p.villages||[]).slice(0,5).map((v,n)=>({type:1,components:[{type:2,style:1,custom_id:"def_village_"+n+"_"+l,label:(v.name||("Village "+(n+1)))+" ("+String(v.coordinates).replace(" ","|")+")"}]}));}
function unitButtons(p,idx,l){const us=DEF_UNITS[p.race]||[];return us.map(u=>({type:1,components:[{type:2,style:1,custom_id:"def_unit_"+idx+"_"+u[0]+"_"+l,label:(l==="ja"?u[2]:u[1])+" — "+Number(p.villages?.[idx]?.troops?.[u[0]]||0)}]}));}

async function handleDiscord(request, env) {
 const raw=await request.text();
 if(!(await verifyDiscordRequest(request,raw)))return new Response("Invalid request signature",{status:401});
 let i;try{i=JSON.parse(raw);}catch{return new Response("Bad Request",{status:400});}
 if(i.type===1)return Response.json({type:1});
 if(String(i.guild_id||"")!==DISCORD_GUILD_ID||String(i.channel_id||"")!==DISCORD_DEFENCE_CHANNEL_ID)return dReply("❌ WORLD Defence is available only in the designated defence channel.\n❌ WORLD Defenceは指定された防衛チャンネルでのみ利用できます。");
 const id=dUser(i);
 try{
  const loaded=await ghJson(env,DISCORD_PLAYERS_PATH),players=loaded.data||{},p=players[id];
  if(i.type===2&&i.data?.name==="def"){
   if(p?.travian_uid){const cd=await centreData(env,p);return dReply(cd.text,sendDefButtons(cd.requests,cd.lang).concat(settingsButtons(cd.lang)));}
   return dReply("🛡 **WORLD Defence**\n\n🇬🇧 "+DTXT.en.choose+"\n🇯🇵 "+DTXT.ja.choose,langButtons());
  }
  
  
  if(i.type===3&&/^def_send_\d+_(en|ja)$/.test(i.data?.custom_id||"")){
   const a=i.data.custom_id.split("_"),rid=Number(a[2]),l=a[3]==="ja"?"ja":"en";
   return Response.json({type:9,data:{custom_id:"def_sendamount_"+rid+"_"+l,title:l==="ja"?"防衛兵を送る":"Send Defence",components:[{type:1,components:[{type:4,custom_id:"amount",style:1,label:l==="ja"?"防衛ポイント":"Defence points",placeholder:"1000",required:true,min_length:1,max_length:8}]}]}});
  }
  if(i.type===5&&/^def_sendamount_\d+_(en|ja)$/.test(i.data?.custom_id||"")){
   const a=i.data.custom_id.split("_"),rid=Number(a[2]),l=a[3]==="ja"?"ja":"en",n=Number(i.data.components?.[0]?.components?.[0]?.value||"");
   if(!Number.isInteger(n)||n<=0||n>99999999)return dReply(l==="ja"?"❌ 1以上の整数を入力してください。":"❌ Enter a whole number greater than 0.");
   const rq=await ghJson(env,"data/defence/requests.json"),list=Array.isArray(rq.data)?rq.data:[],q=list.find(x=>Number(x.id)===rid);
   if(!q||q.status!=="active")return dReply(l==="ja"?"❌ この防衛要請は終了しています。":"❌ This defence request is no longer active.");
   const remaining=Math.max(0,Number(q.required_def||0)-Number(q.collected_def||0));if(remaining<=0)return dReply(l==="ja"?"✅ この防衛要請は既に完了しています。":"✅ This defence request is already covered.");
   const amount=Math.min(n,remaining);q.contributions=Array.isArray(q.contributions)?q.contributions:[];
   q.contributions.push({platform:"discord",user_id:id,player_name:p.player_name,def_points:amount,plan:[],created_at:londonNowText()});
   q.collected_def=q.contributions.reduce((s,z)=>s+Number(z.def_points||0),0);
   await ghSave(env,"data/defence/requests.json",list,rq.sha,"Add WORLD Discord defence contribution");
   return dReply((l==="ja"?"✅ **防衛を登録しました**":"✅ **Defence pledged**")+"\n\n🛡 **"+amount+"**\n🎯 **"+q.target_x+"|"+q.target_y+"**\n📊 "+q.collected_def+" / "+q.required_def);
  }

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

  if(i.type===3&&/^def_lang_(en|ja)$/.test(i.data?.custom_id||"")){const l=i.data.custom_id.endsWith("_ja")?"ja":"en";return dReply("🛡 **WORLD Defence**\n\n"+DTXT[l].wait,regButton(l));}
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
  if(p){const cd=await centreData(env,p);return dReply(cd.text,sendDefButtons(cd.requests,cd.lang).concat(settingsButtons(cd.lang)));}return dReply("Use /def.");
 }catch(e){console.error("Discord Defence error:",e);const l=i.data?.custom_id?.endsWith("_ja")?"ja":"en";const msg=String(e?.message||e||"unknown error").slice(0,500).replace(/`/g,"");return dReply((l==="ja"?"❌ エラー":"❌ Error")+": `"+msg+"`");}
}

const MAX_QUEUE_DELAY_SECONDS = 86400;

function londonNowText() {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/London", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23"
  }).formatToParts(new Date());
  const p = Object.fromEntries(parts.map(x => [x.type, x.value]));
  return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}:${p.second}`;
}

function secondsUntilLondon(localText) {
  // Convert a Europe/London wall-clock timestamp to a delay without assuming
  // that the Worker itself runs in the server timezone.
  const now = new Date();
  const nowParts = londonNowText();
  const target = String(localText || "");
  const parse = s => {
    const m = s.match(/^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})$/);
    return m ? Date.UTC(+m[1], +m[2]-1, +m[3], +m[4], +m[5], +m[6]) : NaN;
  };
  return Math.floor((parse(target) - parse(nowParts)) / 1000);
}

async function queueReminder(env, payload) {
  const delay = secondsUntilLondon(payload.reminder_at);
  if (!Number.isFinite(delay)) throw new Error("Invalid reminder_at");
  if (delay <= 0) {
    await env.DEFENCE_REMINDERS.send(payload, { delaySeconds: 0 });
  } else {
    await env.DEFENCE_REMINDERS.send(payload, {
      delaySeconds: Math.min(delay, MAX_QUEUE_DELAY_SECONDS)
    });
  }
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

  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/London",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23"
  }).formatToParts(new Date());
  const now = Object.fromEntries(parts.map(p => [p.type, p.value]));
  const nowText = `${now.year}-${now.month}-${now.day} ${now.hour}:${now.minute}:${now.second}`;

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

async function dispatch(env, update = null, workflow = GITHUB_WORKFLOW) {
  if (!env.GITHUB_TOKEN) {
    throw new Error("Cloudflare: не задан GITHUB_TOKEN");
  }
  if (!env.TELEGRAM_BOT_TOKEN) {
    throw new Error("Cloudflare: не задан TELEGRAM_BOT_TOKEN");
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
    throw new Error(`GitHub API ${response.status}: ${details.slice(0, 1500)}`);
  }
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
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "GET" && url.pathname === "/discord/register") {
      try {
        const commands = await registerDiscordCommands(env);
        return Response.json({ ok: true, commands });
      } catch (error) {
        return Response.json({ ok: false, error: String(error) }, { status: 500 });
      }
    }

    if (request.method === "POST" && url.pathname === "/discord") {
      return handleDiscord(request, env);
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
        const remaining = secondsUntilLondon(item.reminder_at);
        if (Number.isFinite(remaining) && remaining > 2) {
          message.retry({ delaySeconds: Math.min(remaining, MAX_QUEUE_DELAY_SECONDS) });
          continue;
        }
        await sendPrivateReminder(env, item);
        message.ack();
      } catch (error) {
        console.error("Defence reminder failed:", error instanceof Error ? error.message : String(error));
        message.retry({ delaySeconds: 60 });
      }
    }
  }
};
