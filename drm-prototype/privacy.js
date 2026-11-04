'use strict';
const {getDomain}=require('tldts');
const DEFAULT_HOSTS=['doubleclick.net','googlesyndication.com','googleadservices.com','adnxs.com','taboola.com','outbrain.com','scorecardresearch.com','adsrvr.org','criteo.com','amazon-adsystem.com','yieldmo.com','casalemedia.com','rubiconproject.com','pubmatic.com','openx.net','smartadserver.com','bidswitch.net','quantserve.com','moatads.com','demdex.net','advertising.com','media.net','lijit.com','serving-sys.com','3lift.com','teads.tv'];
const TRACK=new Set(['fbclid','gclid','dclid','msclkid','twclid','igshid','mc_cid','mc_eid']);
function host(url){try{return new URL(url).hostname.toLowerCase();}catch{return '';}}
function sameSite(a,b){a=host(a);b=host(b);return Boolean(a&&b&&(a===b||(getDomain(a,{allowPrivateDomains:true})||a)===(getDomain(b,{allowPrivateDomains:true})||b)));}
function amazon(h){return ['primevideo.com','amazon.com','amazon.de','amazon.co.uk'].some(d=>h===d||h.endsWith('.'+d));}
function thirdParty(url,first){if(!host(first))return true;return !sameSite(url,first)&&!(amazon(host(url))&&amazon(host(first)));}
function parseFilters(raw){if(Buffer.byteLength(raw,'utf8')>12000000)throw Error('Die Filterliste darf maximal 12 MB groß sein.');const hosts=new Set();let skipped=0;
 for(let line of raw.replace(/^\uFEFF/,'').split(/\r?\n/)){line=line.trim().toLowerCase();if(!line||line.startsWith('#')||line.startsWith('!')||line.startsWith('['))continue;
 if(line.startsWith('||')){if(!/^\|\|[a-z0-9.-]+\^?$/.test(line)){skipped++;continue;}line=line.slice(2).replace(/\^$/,'');}
 else if(/\s/.test(line)){const p=line.split(/\s+/);if(p.length!==2||!['0.0.0.0','127.0.0.1','::1'].includes(p[0])){skipped++;continue;}line=p[1];}
 if(line.length<=253&&/^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/.test(line))hosts.add(line);else skipped++;
 }return {hosts,skipped};}
function blockedHost(h,hosts){const parts=h.toLowerCase().split('.');for(let i=0;i<parts.length-1;i++)if(hosts.has(parts.slice(i).join('.')))return true;return false;}
function cleanURL(s){try{const u=new URL(s);if(!/^https?:$/.test(u.protocol))return s;for(const key of [...u.searchParams.keys()])if(/^utm_/i.test(key)||TRACK.has(key.toLowerCase()))u.searchParams.delete(key);return u.href;}catch{return s;}}
module.exports={DEFAULT_HOSTS,parseFilters,blockedHost,cleanURL,thirdParty,sameSite,host};
