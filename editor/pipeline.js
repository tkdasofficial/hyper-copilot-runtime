#!/usr/bin/env node
/**
 * Master Video Orchestrator
 * Supports standalone full pipeline execution as well as modular step execution:
 *   node editor/pipeline.js --step prepare
 *   node editor/pipeline.js --step export
 *   node editor/pipeline.js --step sync
 *   node editor/pipeline.js (full automated run)
 */

const prepareModule = require('./prepare_assets.js');
const exportModule = require('./export_video.js');
const syncModule = require('./post_process_sync.js');

const stepArg = process.argv.find((arg) => arg.startsWith('--step=') || arg === '--step');
let requestedStep = null;
if (stepArg) {
  if (stepArg.includes('=')) {
    requestedStep = stepArg.split('=')[1].trim().toLowerCase();
  } else {
    const idx = process.argv.indexOf('--step');
    if (idx !== -1 && process.argv[idx + 1]) {
      requestedStep = process.argv[idx + 1].trim().toLowerCase();
    }
  }
}

async function runFullPipeline() {
  console.log('=== Hyper Copilot: Executing Full Integrated Pipeline ===');
  console.log('\n>>> Starting Step 3: Asset Preparation...');
  await prepareModule.main();

  console.log('\n>>> Starting Step 4: Master MP4 Rendering...');
  await exportModule.main();

  console.log('\n>>> Starting Step 5: Post-Process Drive Upload & Supabase Sync...');
  await syncModule.main();

  console.log('\n=== Hyper Copilot: Pipeline Complete ===');
}

async function main() {
  if (requestedStep === 'prepare' || requestedStep === 'assets') {
    await prepareModule.main();
  } else if (requestedStep === 'export' || requestedStep === 'render') {
    await exportModule.main();
  } else if (requestedStep === 'sync' || requestedStep === 'upload') {
    await syncModule.main();
  } else {
    await runFullPipeline();
  }
}

if (require.main === module) {
  main().catch((err) => {
    console.error(`Pipeline Master Failure: ${err.message}`);
    process.exit(1);
  });
}

module.exports = {
  runFullPipeline,
  prepareModule,
  exportModule,
  syncModule
};
