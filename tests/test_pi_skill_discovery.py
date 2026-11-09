"""The participation catalog uses Pi discovery without starting an agent turn."""
import pytest

from cota.runtime.pi_bridge import PiBridge


@pytest.mark.asyncio
async def test_discovery_returns_only_visible_skill_metadata_without_requests(tmp_path):
    root = tmp_path / 'skills'
    for name, extra in [('visible', ''), ('hidden', 'disable-model-invocation: true\n')]:
        folder = root / name
        folder.mkdir(parents=True)
        (folder / 'SKILL.md').write_text(
            f'---\nname: {name}\ndescription: {name} description\n{extra}---\nSECRET_SOP_BODY\n')
    bridge = PiBridge()
    assert hasattr(bridge, 'discover_skills')
    result = await bridge.discover_skills(str(tmp_path), ['skills'])
    assert result == [{'name': 'visible', 'description': 'visible description'}]


@pytest.mark.asyncio
async def test_discovery_has_no_default_or_outside_skills(tmp_path):
    root = tmp_path / 'skills'
    outside = tmp_path / 'outside'
    root.mkdir()
    outside.mkdir()
    (outside / 'SKILL.md').write_text('---\nname: outside\ndescription: Outside secret\n---\nSOP\n')
    (root / 'escape').symlink_to(outside, target_is_directory=True)
    bridge = PiBridge()
    assert hasattr(bridge, 'discover_skills')
    assert await bridge.discover_skills(str(tmp_path), ['skills']) == []
