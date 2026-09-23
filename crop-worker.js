const THREAD_ID=20;
const OWNER="dmrylezfree-beep", REPO="travian-discord-bot", WORKFLOW="crop_bot.yml", REF="main";
function msg(update){return update?.message || update?.callback_query?.message || null;}
export default {async fetch(request,env){
  if(request.method!=="POST") return new Response("OK");
  let update; try{update=await request.json();}catch{return new Response("OK");}
  const m=msg(update), chat=m?.chat;
  if(!chat) return new Response("OK");
  if(chat.type!=="private" && Number(m.message_thread_id)!==THREAD_ID) return new Response("OK");
  if(update.callback_query?.id){
    fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/answerCallbackQuery`,{
      method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({callback_query_id:update.callback_query.id})
    }).catch(()=>{});
  }
  const r=await fetch(`https://api.github.com/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW}/dispatches`,{
    method:"POST",headers:{Authorization:`Bearer ${env.GITHUB_TOKEN}`,"Accept":"application/vnd.github+json","Content-Type":"application/json","User-Agent":"travian-crop"},
    body:JSON.stringify({ref:REF,inputs:{action:update.callback_query?"callback":"message",thread_id:String(THREAD_ID),update_json:JSON.stringify(update)}})
  });
  if(!r.ok) console.error(await r.text());
  return new Response("OK");
}};
