// Run with DeepSeek Harness's bundled Electron binary in ELECTRON_RUN_AS_NODE mode.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

async function main() {
  const appResources = process.env.DSH_APP_RESOURCES
    || '/Applications/DeepSeek Harness.app/Contents/Resources';
  const packages = path.join(appResources, 'app.asar/dsh/node_modules/@deepseek-ai');
  const { Context } = require(path.join(packages, 'cordis/lib/index.js'));
  const skills = require(path.join(packages, 'dsh-skill/lib/index.js'));
  const filesystem = require(path.join(packages, 'dsh-skill-filesystem/lib/index.js'));
  const runtime = JSON.parse(fs.readFileSync(path.join(packages, 'dsh/package.json'), 'utf8'));
  const dshHome = process.env.DSH_HOME || path.join(os.homedir(), '.dsh');
  const name = process.argv[2] || 'pdf-translate';
  const cwd = process.argv[3] || process.cwd();
  const expectedDirectory = path.join(dshHome, 'skills', name);
  const expectedFile = path.join(expectedDirectory, 'SKILL.md');
  assert.equal(skills.isSkillName(name), true, 'skill name must match DSH kebab-case grammar');
  assert.equal(skills.isSkillName('翻译'), false, 'original Chinese identifier is rejected by DSH');
  assert.equal(fs.existsSync(expectedFile), true, 'installed SKILL.md must exist');

  const ctx = new Context();
  const registry = await ctx.plugin(skills.default);
  let provider;
  try {
    provider = await ctx.plugin(filesystem, { dshHome, watch: false });
    const snapshot = await ctx.skills.snapshot({ cwd });
    assert.equal(snapshot.complete, true, 'DSH filesystem discovery must complete');
    const summary = snapshot.skills.find(skill => skill.name === name);
    assert.ok(summary, 'skill must be discoverable through the actual DSH registry');
    assert.equal(summary.source, 'user-dsh', 'installed user skill must be the selected entry');
    assert.equal(summary.provider, 'filesystem');
    assert.equal(summary.path, fs.realpathSync(expectedFile));
    assert.equal(summary.invocation.userInvocable, true);
    assert.equal(summary.invocation.modelInvocable, true);
    const loaded = await ctx.skills.get(name, { cwd });
    assert.ok(loaded && loaded.content.trim(), 'registry must load the complete skill body');
    assert.equal(loaded.resourceBase.kind, 'directory');
    assert.equal(loaded.resourceBase.path, expectedDirectory);
    const rendered = skills.renderSkillContent(loaded);
    assert.ok(rendered.includes(`<skill_content name="${name}">`));
    assert.ok(rendered.includes(`Base directory for this skill: ${expectedDirectory}`));
    assert.ok(rendered.includes(loaded.content));
    console.log(JSON.stringify({
      status: 'passed',
      dshVersion: runtime.version,
      skill: summary.name,
      source: summary.source,
      provider: summary.provider,
      path: summary.path,
      resourceBase: loaded.resourceBase,
      invocation: summary.invocation,
      contentCharacters: loaded.content.length,
      renderedCharacters: rendered.length,
      catalogComplete: snapshot.complete,
      originalChineseNameAccepted: false
    }, null, 2));
  } finally {
    if (provider) await provider.dispose();
    await registry.dispose();
  }
}
main().catch(error => {
  console.error(error.stack || String(error));
  process.exitCode = 1;
});
