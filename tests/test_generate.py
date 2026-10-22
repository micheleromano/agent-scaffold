import json

import pytest

from agent_scaffold.generate import adopt_claude_md, blocks, can_adopt_claude_md, generate
from agent_scaffold.models import AGENTS, MCP_SERVERS, ROLES, STACKS, Answers

from .helpers import MINIMAL, files_by_path, frontmatter, frontmatter_list, make_answers


def test_full_setup_writes_every_file() -> None:
    assert set(files_by_path(make_answers())) == {
        "AGENTS.md",
        "CLAUDE.md",
        "CLAUDE.local.md",
        ".mcp.json",
        ".gitignore",
        ".claude/settings.json",
        ".claude/rules/code-style.md",
        ".claude/rules/testing.md",
        ".claude/rules/backend.md",
        ".claude/skills/plan/SKILL.md",
        ".claude/skills/review/SKILL.md",
        ".claude/skills/ship/SKILL.md",
        ".claude/skills/ci/SKILL.md",
        ".claude/rules/humane-design.md",
        ".claude/agents/humane-design-reviewer.md",
        ".claude/agents/code-reviewer.md",
        ".claude/agents/security-auditor.md",
        ".claude/hooks/block_dangerous.py",
        ".claude/hooks/format_on_edit.py",
    }


def test_minimal_setup_writes_only_the_core_files() -> None:
    assert set(files_by_path(Answers.from_dict(MINIMAL))) == {
        "AGENTS.md",
        "CLAUDE.md",
        "CLAUDE.local.md",
        ".gitignore",
        ".claude/settings.json",
        ".claude/rules/code-style.md",
        ".claude/rules/testing.md",
        ".claude/skills/plan/SKILL.md",
        ".claude/skills/review/SKILL.md",
        ".claude/skills/ship/SKILL.md",
        ".claude/skills/ci/SKILL.md",
        ".claude/rules/humane-design.md",
        ".claude/agents/humane-design-reviewer.md",
    }


@pytest.mark.parametrize("stack", list(STACKS))
def test_every_preset_renders_valid_files(stack: str) -> None:
    preset = STACKS[stack]
    answers = make_answers(
        stacks=[stack],
        test_cmd=preset.test,
        lint_cmd=preset.lint,
        format_cmd=preset.format,
        format_on_edit=bool(preset.format),
        agents=list(AGENTS),
        mcp_servers=list(MCP_SERVERS),
    )
    files = files_by_path(answers)
    json.loads(files[".claude/settings.json"])
    json.loads(files[".mcp.json"])
    assert frontmatter_list(files[".claude/rules/code-style.md"], "paths") == list(preset.globs)
    assert frontmatter_list(files[".claude/rules/testing.md"], "paths") == list(preset.test_globs)
    for path, content in files.items():
        assert "TODO" not in content or path in ("AGENTS.md", "CLAUDE.local.md"), path
        if path.endswith(".py"):
            compile(content, path, "exec")


def test_custom_extensions_without_a_preset() -> None:
    files = files_by_path(Answers.from_dict(MINIMAL))
    assert "- *.ex files" in files["AGENTS.md"]
    assert frontmatter_list(files[".claude/rules/code-style.md"], "paths") == ["**/*.ex"]
    assert frontmatter_list(files[".claude/rules/testing.md"], "paths") == ["**/*test*.ex", "**/*spec*.ex"]


def test_empty_commands_are_left_out() -> None:
    files = files_by_path(Answers.from_dict(MINIMAL))
    assert files["AGENTS.md"].startswith("# tiny\n\n## Stack\n\n- *.ex files\n\n## Architecture\n")
    assert json.loads(files[".claude/settings.json"])["permissions"]["allow"] == []
    assert "Run `" not in files[".claude/skills/review/SKILL.md"]


def test_settings_json_permissions_and_hooks() -> None:
    settings = json.loads(files_by_path(make_answers())[".claude/settings.json"])
    assert settings["$schema"] == "https://json.schemastore.org/claude-code-settings.json"
    assert settings["permissions"]["allow"] == [
        "Bash(npm test)",
        "Bash(npm test *)",
        "Bash(npm run lint)",
        "Bash(npm run lint *)",
    ]
    assert "Read(./.env)" in settings["permissions"]["deny"]
    pre, post = settings["hooks"]["PreToolUse"][0], settings["hooks"]["PostToolUse"][0]
    assert pre["matcher"] == "Bash"
    assert pre["hooks"][0]["command"] == 'python3 "${CLAUDE_PROJECT_DIR}/.claude/hooks/block_dangerous.py"'
    assert post["matcher"] == "Edit|Write"


def test_settings_json_has_no_hooks_key_when_none_chosen() -> None:
    settings = json.loads(
        files_by_path(make_answers(block_dangerous=False, format_on_edit=False))[".claude/settings.json"]
    )
    assert "hooks" not in settings


def test_mcp_json_lists_selected_servers() -> None:
    servers = json.loads(files_by_path(make_answers())[".mcp.json"])["mcpServers"]
    assert set(servers) == {"github", "sentry"}
    assert servers["github"] == {
        "type": "http",
        "url": "https://api.githubcopilot.com/mcp/",
        "headers": {"Authorization": "Bearer ${GITHUB_PAT}"},
    }


def test_every_remote_mcp_server_declares_its_type() -> None:
    # A `url` without `type` is read as a stdio server and fails to load.
    for server in MCP_SERVERS.values():
        assert "url" not in server.config or server.config["type"] in ("http", "sse")


def test_local_notes_list_required_env_vars() -> None:
    assert "GITHUB_PAT" in files_by_path(make_answers())["CLAUDE.local.md"]
    assert "environment variables" not in files_by_path(make_answers(mcp_servers=["sentry"]))["CLAUDE.local.md"]


@pytest.mark.parametrize("name", ["acme: ordering", 'quote "this"', "multi # hash"])
def test_frontmatter_survives_awkward_project_names(name: str) -> None:
    files = files_by_path(make_answers(name=name, agents=list(AGENTS)))
    for path in [f".claude/agents/{key}.md" for key in AGENTS] + [".claude/skills/review/SKILL.md"]:
        meta = frontmatter(files[path])
        assert name in json.loads(meta["description"]), path
        assert meta["name"] in (*AGENTS, "review")


def test_gitignore_is_merged_not_replaced() -> None:
    gitignore = next(f for f in generate(make_answers()) if f.path == ".gitignore")
    assert gitignore.merge_lines
    assert gitignore.content.splitlines() == ["CLAUDE.local.md", ".claude/settings.local.json"]


def test_humane_design_rule_is_always_generated_and_loaded() -> None:
    assert ".claude/rules/humane-design.md" in files_by_path(Answers.from_dict(MINIMAL))
    rule = files_by_path(make_answers())[".claude/rules/humane-design.md"]
    # No `paths:` frontmatter, so Claude Code loads it every session rather than per file.
    assert not rule.startswith("---")
    assert "https://www.humanetech.com/humane-product-design" in rule
    assert "## What we build" in rule
    assert 'in `AGENTS.md` under "How to work"' in rule


def test_humane_design_reviewer_covers_all_seven_principles() -> None:
    agent = files_by_path(make_answers(agents=[]))[".claude/agents/humane-design-reviewer.md"]
    assert frontmatter(agent)["tools"] == "Read, Glob, Grep"
    for n in range(1, 8):
        assert f"\n{n}. **" in agent


def test_claude_md_imports_agents_md_first() -> None:
    claude = files_by_path(make_answers())["CLAUDE.md"]
    # Claude Code only reads AGENTS.md through this import when CLAUDE.md or CLAUDE.local.md exists.
    assert claude.splitlines()[0] == "@AGENTS.md"
    assert "`humane-design-reviewer` for anything people see or use, `code-reviewer`, `security-auditor`." in claude
    assert "block destructive shell commands and format each file after you edit it" in claude


def test_claude_md_leaves_out_hooks_when_none_chosen() -> None:
    claude = files_by_path(make_answers(block_dangerous=False, format_on_edit=False))["CLAUDE.md"]
    assert "Hooks" not in claude


def test_agents_md_has_the_working_principles() -> None:
    agents = files_by_path(make_answers())["AGENTS.md"]
    assert "## How to work" in agents
    for principle in (
        "Think before coding",
        "Keep it simple",
        "Make surgical changes",
        "Work toward a verifiable goal",
        "Keep people in control",
        "Use current, compatible dependencies",
    ):
        assert f"**{principle}.**" in agents
    assert "https://x.com/karpathy/status/2015883857489522876" in agents


@pytest.mark.parametrize("skill", ["plan", "review", "ship"])
def test_skills_are_user_invoked_only(skill: str) -> None:
    # Skills with side effects (ship) or that need a deliberate start (plan, review) must not auto-trigger.
    meta = frontmatter(files_by_path(make_answers())[f".claude/skills/{skill}/SKILL.md"])
    assert meta["name"] == skill
    assert meta["disable-model-invocation"] == "true"


def test_ship_runs_configured_checks_and_waits_for_confirmation() -> None:
    ship = files_by_path(make_answers())[".claude/skills/ship/SKILL.md"]
    assert "`npm run lint`" in ship
    assert "`npm test`" in ship
    assert "**Wait for their go-ahead**" in ship
    assert "`code-reviewer` subagent" in ship


def test_ship_without_commands_asks_how_to_verify() -> None:
    ship = files_by_path(Answers.from_dict(MINIMAL))[".claude/skills/ship/SKILL.md"]
    assert "no test command is configured" in ship
    assert "code-reviewer" not in ship


UNDECIDED = {"name": "habit", "description": "A habit tracker for students.", "stack_undecided": True}


def test_undecided_stack_adds_the_choose_stack_skill() -> None:
    files = files_by_path(Answers.from_dict(UNDECIDED))
    skill = files[".claude/skills/choose-stack/SKILL.md"]
    assert frontmatter(skill)["disable-model-invocation"] == "true"
    assert "Propose 2 or 3 options" in skill
    assert "Wait for the user to choose" in skill
    assert ".claude/skills/choose-stack/SKILL.md" not in files_by_path(make_answers())


def test_undecided_stack_is_recorded_in_agents_and_claude_md() -> None:
    files = files_by_path(Answers.from_dict(UNDECIDED))
    assert "## Stack\n\nNot decided yet." in files["AGENTS.md"]
    assert "## Commands" not in files["AGENTS.md"]
    assert "run `/choose-stack` before writing application code" in files["CLAUDE.md"]
    assert "Not decided yet" not in files_by_path(make_answers())["AGENTS.md"]
    assert "/choose-stack" not in files_by_path(make_answers())["CLAUDE.md"]


def test_undecided_stack_rules_load_everywhere_until_scoped() -> None:
    # Without paths: frontmatter, Claude Code loads a rule for every file; /choose-stack adds the paths later.
    files = files_by_path(Answers.from_dict(UNDECIDED))
    assert files[".claude/rules/code-style.md"].startswith("# Code style")
    assert files[".claude/rules/testing.md"].startswith("# Testing")


MY_CLAUDE_MD = "# treesdolisten\n\nA frozen static blog on Cloudflare Pages.\n"


def test_adopting_claude_md_moves_it_into_agents_md_with_the_principles() -> None:
    files = {f.path: f.content for f in adopt_claude_md(generate(make_answers()), MY_CLAUDE_MD)}
    assert files["AGENTS.md"].startswith(MY_CLAUDE_MD + "\n<!-- agent-scaffold:principles -->\n## How to work\n")
    assert "## Stack" not in files["AGENTS.md"]  # the user's own description replaces the generated one
    assert files["CLAUDE.md"].startswith("@AGENTS.md\n")


def test_adopting_does_not_duplicate_existing_principles() -> None:
    mine = MY_CLAUDE_MD + "\n## How to work\n\n1. My own rules.\n"
    agents = next(f for f in adopt_claude_md(generate(make_answers()), mine) if f.path == "AGENTS.md")
    assert agents.content == mine
    assert agents.content.count("## How to work") == 1


@pytest.mark.parametrize(
    ("existing", "agents_md_exists", "expected"),
    [
        (MY_CLAUDE_MD, False, True),
        (MY_CLAUDE_MD, True, False),  # an existing AGENTS.md would be clobbered
        ("@AGENTS.md\n\nnotes\n", False, False),  # already imports one
    ],
)
def test_can_adopt_claude_md(existing: str, *, agents_md_exists: bool, expected: bool) -> None:
    assert can_adopt_claude_md(existing, agents_md_exists) is expected


@pytest.mark.parametrize("role", [r for r in ROLES if r != "other"])
def test_each_role_adds_its_conventions_rule(role: str) -> None:
    files = files_by_path(make_answers(role=role))
    rule = files[f".claude/rules/{role}.md"]
    assert rule.startswith("# ")
    assert rule.count("\n- ") >= 4
    assert not rule.startswith("---")  # loads every session in this project


def test_other_role_adds_no_rule() -> None:
    files = files_by_path(make_answers(role="other"))
    assert not any(path.startswith(".claude/rules/") and path[14:-3] in ROLES for path in files)


def test_fullstack_rule_combines_backend_and_frontend() -> None:
    rule = files_by_path(make_answers(role="fullstack"))[".claude/rules/fullstack.md"]
    assert "## Backend and API" in rule
    assert "## Frontend" in rule


def test_llm_rule_covers_evals_and_untrusted_output() -> None:
    rule = files_by_path(make_answers(role="llm"))[".claude/rules/llm.md"]
    assert "run the eval set" in rule
    assert "untrusted input" in rule


def test_conventions_render_as_bullets() -> None:
    rules = "Use react-router loaders instead of `useEffect`; Never edit files in src/generated: run codegen"
    agents = files_by_path(make_answers(conventions=rules))["AGENTS.md"]
    section = agents.split("## Conventions\n\n")[1].split("\n\n")[0]
    assert section == (
        "- Use react-router loaders instead of `useEffect`\n- Never edit files in src/generated: run codegen"
    )


def test_missing_conventions_leave_a_helpful_todo() -> None:
    agents = files_by_path(make_answers(conventions=""))["AGENTS.md"]
    assert 'TODO: rules an agent wouldn\'t guess, e.g. "prefer react-router loaders over useEffect".' in agents


def test_npx_mcp_servers_are_pinned_to_a_version() -> None:
    for key, server in MCP_SERVERS.items():
        for arg in server.config.get("args", []):
            if arg.startswith("@") and arg.count("@") == 2:
                version = arg.rsplit("@", 1)[1]
                assert version[0].isdigit(), f"{key} must pin an exact version, not {version!r}"


def test_dependency_principle_says_to_look_up_versions_not_record_them() -> None:
    principles = blocks(files_by_path(make_answers())["AGENTS.md"])["principles"]
    assert "look up the latest stable version" in principles
    assert "don't write version numbers into `AGENTS.md`" in principles


def test_choose_stack_checks_versions_and_records_names_only() -> None:
    skill = files_by_path(make_answers(stack_undecided=True, stacks=[], format_on_edit=False))[
        ".claude/skills/choose-stack/SKILL.md"
    ]
    assert "look up the latest stable version of each main library" in skill
    assert "framework names (no version numbers)" in skill


def test_ci_skill_runs_the_configured_checks_with_looked_up_action_versions() -> None:
    ci = files_by_path(make_answers(install_cmd=""))[".claude/skills/ci/SKILL.md"]
    assert "disable-model-invocation: true" in ci
    assert "`AGENTS.md`: lint `npm run lint`, test `npm test`." in ci
    assert "`.github/workflows/ci.yml`" in ci
    assert "releases/latest" in ci
    assert "otherwise use the full release tag" in ci
    assert "${{ secrets.NAME }}" in ci
    assert "**wait for their go-ahead**" in ci
    assert "choose-stack" not in ci


def test_ci_skill_waits_for_an_undecided_stack() -> None:
    ci = files_by_path(Answers(name="idea", description="", stack_undecided=True))[".claude/skills/ci/SKILL.md"]
    assert "run `/choose-stack` first, then stop" in ci
    assert "Take the commands from `AGENTS.md`. If" in ci
