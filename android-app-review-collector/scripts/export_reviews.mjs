import fs from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';
import sharp from 'sharp';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

// Copy scripts/ AND assets/ together to a task build directory when linking the
// environment-owned artifact runtime. Do not install it globally or bundle it.
const spec = JSON.parse(await fs.readFile(new URL('../assets/workbook-format.json', import.meta.url), 'utf8'));
const [sourceArg, finalArg, ...options] = process.argv.slice(2);
if (!sourceArg || !finalArg || options.length && (options.length !== 2 || options[0] !== '--config')) {
  throw new Error('Usage: node scripts/export_reviews.mjs <collection-dir> <output.xlsx> [--config <CDP-adapter.json>]');
}
const source = path.resolve(sourceArg), finalPath = path.resolve(finalArg), dest = path.dirname(finalPath);
if (path.extname(finalPath).toLowerCase() !== '.xlsx') throw new Error('Output must be .xlsx; CSV cannot embed images');
const exists = async file => {try {await fs.access(file); return true;} catch {return false;}};
let records, meta;
if (await exists(path.join(source, 'reviews.jsonl'))) {
  if (options[0] !== '--config') throw new Error('CDP export requires --config <adapter.json>');
  const cfg = JSON.parse((await fs.readFile(options[1], 'utf8')).replace(/^\uFEFF/,''));
  const state = JSON.parse(await fs.readFile(path.join(source, 'state.json'), 'utf8'));
  const raw = (await fs.readFile(path.join(source, 'reviews.jsonl'), 'utf8')).split(/\r?\n/).filter(Boolean).map(s=>JSON.parse(s));
  const placeholders = new Set(['匿名买家','匿名用户','匿名','用户已注销'].map(name=>createHash('sha256').update(cfg.platform+'|'+cfg.target_id+'|'+name).digest('hex').slice(0,20)));
  if (raw.some(r=>['platform','target_id','sort_filter'].some(k=>r[k]!==cfg[k]))) throw new Error('Input identity mismatch');
  if (new Set(raw.map(r=>r.key)).size!==raw.length || raw.some(r=>!r.key) || state.unique_reviews!==raw.length) throw new Error('Duplicate or missing review key, or checkpoint mismatch');
  records = raw.map(r=>({...r, authorLabel:placeholders.has(r.author_key)?'匿名买家（页面未区分）':r.author_key?'买家-'+r.author_key.slice(0,10):'未展示', screenshots:[r.evidence]}));
  meta = {productName:cfg.product_name||cfg.platform+'商品', sourceUrl:cfg.source_url||raw[0]?.source_url||'', targetId:cfg.target_id,
    sortFilter:cfg.sort_filter, capturedAt:state.updated_at||'', reason:state.reason||'未记录'};
} else {
  const data = JSON.parse(await fs.readFile(path.join(source, 'reviews.json'), 'utf8'));
  records = data.reviews.map(r=>({...r, authorLabel:r.author||'未展示', screenshots:[...new Set(r.screenshots||[])]}));
  if (new Set(records.map(r=>JSON.stringify([r.text,r.sku_raw]))).size!==records.length || data.count!==records.length) throw new Error('Duplicate reviews or checkpoint mismatch');
  meta = {productName:data.product_name||'商品', sourceUrl:data.source_url||'', targetId:data.target_id||'',
    sortFilter:[data.sort||'',data.filters||''].join('；'), capturedAt:data.captured_at||'', reason:data.status||'未记录'};
}
if (!records.length || records.length>1048570) throw new Error('Empty input or Excel row limit exceeded; split into batches without dropping records');
const evidencePath = async relative => {
  const normalized = String(relative).replaceAll('\\','/');
  if (!normalized || path.isAbsolute(normalized) || normalized.includes(':')) throw new Error('Evidence must be relative');
  const file = await fs.realpath(path.resolve(source,normalized));
  const rel = path.relative(await fs.realpath(source),file);
  if (rel.startsWith('..'+path.sep) || rel==='..' || path.isAbsolute(rel)) throw new Error('Evidence outside collection directory');
  return file;
};
for (const r of records) {
  if (!r.text?.trim() || !r.screenshots.length) throw new Error('Review has no text or screenshot');
  for (const file of r.screenshots) await evidencePath(file);
}
const literal = v => {
  if (typeof v==='string' && (v.length>32767 || /[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(v))) throw new Error('Source exceeds Excel cell limits; do not truncate');
  return typeof v==='string' && v.startsWith('=')?"'"+v:v;
};
const wb=Workbook.create(), sh=wb.worksheets.add(spec.sheet), n=records.length;
sh.showGridLines=false;
sh.getRange(`A1:I${n+6}`).format.font={name:spec.font,size:spec.font_size,color:'#'+spec.text_color};
const parsedTime=new Date(meta.capturedAt);
const moment=Number.isNaN(parsedTime.valueOf())?meta.capturedAt:parsedTime.toLocaleString('sv-SE',{timeZone:'Asia/Shanghai',hour12:false})+'（北京时间）';
const notes=[meta.productName+'买家评价', `本次采集 ${n} 条。${meta.sortFilter}。采集时间：${moment}。停止原因：${meta.reason}。`,
  `来源：${meta.sourceUrl}${meta.targetId?'。商品ID：'+meta.targetId:''}`,spec.note];
for(let i=0;i<notes.length;i++) sh.getRange(`A${i+2}`).values=[[literal(notes[i])]];
sh.getRange('A2').format.font={name:spec.font,size:16,bold:true,color:'#'+spec.text_color};
sh.getRange('A2').format.rowHeight=27;
sh.getRange('A6:I6').values=[spec.headings];
sh.getRange('A6:I6').format={fill:'#'+spec.header_color,font:{name:spec.font,size:spec.font_size,bold:true,color:'#FFFFFF'},rowHeight:30,verticalAlignment:'center',horizontalAlignment:'center'};
const rows=records.map((r,i)=>[i+1,r.authorLabel,r.date_raw||'未展示',r.sku_raw||'未展示',r.text,r.rating_raw||'未展示文字星级','',r.screenshots.join('\n'),r.review_id||'未提供'].map(literal));
sh.getRange(`A7:I${n+6}`).values=rows;
sh.getRange(`A7:I${n+6}`).format.wrapText=true;
sh.getRange(`A7:I${n+6}`).format.verticalAlignment='top';
for(let c=0;c<9;c++) sh.getRangeByIndexes(0,c,n+6,1).format.columnWidth=spec.widths[c];
sh.freezePanes.freezeRows(6);sh.freezePanes.freezeColumns(2);
sh.tables.add(`A6:I${n+6}`,true,'Reviews');
const lines=(value,width)=>String(value).split('\n').reduce((sum,line)=>sum+Math.max(1,Math.ceil([...line].reduce((n,c)=>n+(c.charCodeAt(0)>255?2:1),0)/width)),0);
for(let i=0;i<n;i++){
  const r=records[i], row=i+7;
  const picks=r.screenshots.length===1?r.screenshots:[r.screenshots[0],r.screenshots.at(-1)];
  const maxWidth=picks.length===1?spec.image_max_width:Math.floor((spec.image_max_width-8)/2);
  let heightPx=136, x=4;
  for(const relative of picks){
    const bytes=await fs.readFile(await evidencePath(relative)), image=sharp(bytes).rotate(), info=await image.metadata();
    const ratio=Math.min(1,maxWidth/info.width,spec.image_max_height/info.height), width=Math.max(1,Math.round(info.width*ratio)), height=Math.max(1,Math.round(info.height*ratio));
    const jpeg=await image.resize(width,height).jpeg({quality:88}).toBuffer();
    sh.images.add({dataUrl:'data:image/jpeg;base64,'+jpeg.toString('base64'),anchor:{from:{row:row-1,col:6,rowOffsetPx:4,colOffsetPx:x},extent:{widthPx:width,heightPx:height}}});
    heightPx=Math.max(heightPx,height+12);x+=width+8;
  }
  heightPx=Math.max(heightPx,lines(r.text,74)*18+16,lines(r.sku_raw||'',38)*18+16,lines(r.screenshots.join('\n'),28)*18+16);
  if(heightPx>540) throw new Error(`Review ${i+1} needs a multirow layout; do not crop text or screenshots`);
  sh.getRange(`A${row}:I${row}`).format.rowHeightPx=heightPx;
  if(i%2===1)sh.getRange(`A${row}:I${row}`).format.fill='#'+spec.stripe_color;
}
wb.recalculate();
console.log((await wb.inspect({kind:'table',range:`${spec.sheet}!A6:F9`,tableMaxRows:4,tableMaxCols:6,maxChars:1000})).ndjson);
console.log((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:20},summary:'final error scan'})).ndjson);
await fs.mkdir(dest,{recursive:true});
for(const start of [...new Set([6,Math.max(6,Math.floor(n/2)+5),Math.max(6,n+4)])]){
  const png=await wb.render({sheetName:spec.sheet,range:`A${start}:I${Math.min(n+6,start+2)}`,scale:1,format:'png'});
  await fs.writeFile(path.join(dest,`preview-${start}.png`),new Uint8Array(await png.arrayBuffer()));
}
await(await SpreadsheetFile.exportXlsx(wb)).save(finalPath);
console.log('EXPORTED',n,finalPath);
