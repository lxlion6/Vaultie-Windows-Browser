'use strict';
const fs=require('node:fs/promises'),path=require('node:path');
const CLEAN_AT=3800000000,HARD_LIMIT=5000000000;
async function folderBytes(root){let total=0;async function walk(dir){let entries;try{entries=await fs.readdir(dir,{withFileTypes:true});}catch{return;}for(const e of entries){if(e.isSymbolicLink()||e.name==='Downloads')continue;const p=path.join(dir,e.name);if(e.isDirectory())await walk(p);else if(e.isFile()){try{total+=(await fs.lstat(p)).size;}catch{}}}}await walk(root);return total;}
async function checkStorage(root,profiles,force=false){const before=await folderBytes(root);if(force||before>=CLEAN_AT)for(const profile of profiles)await profile.clearCache();const after=force||before>=CLEAN_AT?await folderBytes(root):before;return {before,bytes:after,freed:Math.max(0,before-after),limit:HARD_LIMIT,cleanAt:CLEAN_AT,over:after>=HARD_LIMIT};}
module.exports={folderBytes,checkStorage,CLEAN_AT,HARD_LIMIT};
