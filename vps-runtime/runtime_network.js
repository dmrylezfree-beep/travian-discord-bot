const original=globalThis.fetch;
globalThis.fetch=(input,options)=>{
  const host=new URL(typeof input==='string'||input instanceof URL?input:input.url).hostname;
  if(host==='github.com'||host.endsWith('.github.com')||host.endsWith('.githubusercontent.com')||host.endsWith('.workers.dev')) {
    return Promise.reject(Error('External state dependency disabled on VPS'));
  }
  return original(input,options);
};
