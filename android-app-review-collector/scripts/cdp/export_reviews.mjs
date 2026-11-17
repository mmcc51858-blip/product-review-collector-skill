// Backward-compatible entry point; both routes now use the same workbook.
const [source,config,output]=process.argv.slice(2);
if(!source || !config || !output)throw new Error('Usage: node scripts/cdp/export_reviews.mjs <collection-dir> <adapter.json> <output.xlsx>');
process.argv=[process.argv[0],process.argv[1],source,output,'--config',config];
await import('../export_reviews.mjs');
