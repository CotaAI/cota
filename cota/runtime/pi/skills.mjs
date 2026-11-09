/** Pi's Skill components with Cota's explicit Bot resource boundary. */
import { realpath } from 'node:fs/promises';
import { resolve, relative, isAbsolute, sep } from 'node:path';
import { loadSkillsFromDir, loadSkills, formatSkillsForPrompt } from '@earendil-works/pi-coding-agent';

export const within = (root, path) => {
  const part = relative(root, path);
  return part === '' || (!isAbsolute(part) && part !== '..' && !part.startsWith('..' + sep));
};

export async function createSkillResources({cwd = process.cwd(), skillPaths = []}) {
  const roots = [];
  for (const path of skillPaths) {
    try { roots.push(await realpath(resolve(cwd, path))); }
    catch (error) { if (error.code !== 'ENOENT') throw error; }
  }
  // Use Pi discovery/validation first, then admit canonical files before Pi
  // resolves name collisions. An outside symlink must not shadow a Bot Skill.
  const candidates = [], diagnostics = [];
  async function addDiagnostics(items) {
    for (const item of items) {
      let admitted = false;
      try {
        const file = await realpath(item.path);
        admitted = roots.some(root => within(root, file));
      } catch {}
      // Parser diagnostics can embed source lines. Never expose outside text.
      diagnostics.push(admitted ? item : {type: 'warning', path: item.path,
        message: 'Skill diagnostic excluded: outside the Bot resource roots'});
    }
  }
  for (const root of roots) {
    const discovered = loadSkillsFromDir({dir: root, source: 'bot'});
    await addDiagnostics(discovered.diagnostics);
    for (const skill of discovered.skills) {
      const file = await realpath(skill.filePath);
      const base = await realpath(skill.baseDir);
      if (!roots.some(allowed => within(allowed, file) && within(allowed, base))) {
        diagnostics.push({type: 'warning', path: skill.filePath, message: 'Skill is outside the Bot resource roots'});
        continue;
      }
      candidates.push(file);
    }
  }
  const loaded = loadSkills({cwd, agentDir: cwd, skillPaths: candidates, includeDefaults: false});
  await addDiagnostics(loaded.diagnostics);
  const skills = loaded.skills;
  const prompt = formatSkillsForPrompt(skills);
  return {skills, diagnostics, prompt};
}
