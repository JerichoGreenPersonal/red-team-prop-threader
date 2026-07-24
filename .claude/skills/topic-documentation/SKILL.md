---
name: topic-documentation
description: Use when the user wants to document a project topic, system, decision, or concept in writing for non-code readers (executive, manager, or engineering audiences) rather than generating a code reference. Triggers on /topic-documentation, "document this topic", "write a topic doc", "explain X for the team", "write up Y for execs".
---

# Topic Documentation

Interactive workflow that interviews the user about a topic, searches the codebase to ground the writing in reality, and produces a human-readable Markdown document at one or more density levels: Executive, Manager, and Engineering.

This is a **discussion** documentation skill, not a code reference skill. The output is prose meant to be read by humans, not API documentation or auto-generated code docs.

## When to Use

Use when:

- The user wants to explain a project area, architecture, decision, workflow, or concept in writing.
- The audience includes non-engineers (executives, managers) or engineers who need a conceptual overview rather than a code dive.
- A written record is needed for onboarding, alignment, handoff, or future reference.

Do not use for:

- API or function-level reference docs (use code comments, docstrings, or generated docs).
- Quick informal answers (just answer in chat).
- Live architecture diagrams that should auto-update from code.

## Output Location and Naming

Write the document to:

```
docs/topics/YYYYMMDD-<concise-topic-slug>.md
```

- `YYYYMMDD` is today's date in the user's local time zone.
- `<concise-topic-slug>` is lowercase kebab-case, 2 to 5 words, descriptive of the topic.

If `docs/topics/` does not exist, create it before writing the file.

Example: `docs/topics/20260521-version-bump-workflow.md`

## Writing Style Rules

These rules are non-negotiable. The output should read like a thoughtful human explained the topic over coffee, not like a robot generated it.

### Voice and Cadence

- Aim for a Flesch Reading Ease score around 60. Mix short and medium sentences. Average sentence length is roughly 15 to 20 words.
- Use simple, common words where possible. Pick "use" over "utilize", "help" over "facilitate", "show" over "demonstrate".
- Prefer active voice. "The system caches results" beats "Results are cached by the system."
- Vary sentence rhythm. Avoid stacks of identical-length sentences.
- Address the reader naturally. "You" and "we" are fine when they fit.
- No hype, no filler, no marketing language. No words like "exciting", "powerful", "robust", "seamless".

### Character Restrictions

- **ASCII only.** No non-ASCII characters anywhere in the document.
- No emojis.
- No em-dashes. Use a comma, semicolon, period, or split the sentence.
- No en-dashes. Use a hyphen-minus for ranges and inline modifiers.
- No ellipsis character. Write "and so on" or rephrase.
- No smart quotes. Use straight ASCII single and double quotes only.
- No bullet glyphs other than the Markdown dash.

If a sentence tempts you toward any of those, rewrite it.

### Formatting

- Use Markdown headings, bold for emphasis, tables for comparisons, and bulleted or numbered lists for sequences.
- Section headings use sentence case, not title case.
- Code-style backticks are fine for filenames, command names, and technical terms (for example, `pyproject.toml`).
- No raw code blocks in any density level. This skill describes concepts, not implementations.

## Density Levels

Each document includes one or more density levels. Always confirm with the user which they want. If they want more than one, include them in this order: Executive, then Manager, then Engineering.

### Executive

Very high level and conceptual. Two to five short paragraphs. Answers:

- What is this thing?
- Why does it matter to the business or the project?
- What is the cost or value at stake?

No jargon. No implementation details. A non-technical reader should walk away with the gist.

### Manager

More detailed than Executive, but not dense. Roughly half a page to a full page. Answers:

- How does this work at a workflow level?
- Who owns it, who depends on it, and where does it fit in the broader system?
- What are the trade-offs?
- What are the risks or open questions?

Light technical vocabulary is fine. Tables help here.

### Engineering

Conceptual depth, one to several pages. Answers:

- What components, services, or modules are involved and how do they relate?
- What data flows where, and what triggers what?
- What invariants hold? What can fail, and how does the system respond?
- What design decisions were made and why? What alternatives were considered and rejected?

**No raw code.** Describe concepts in depth. Refer to file paths, module names, and configuration files by name, but do not paste their contents. If the reader wants the code, they can open the file.

## Workflow

### 1. Interview the user

Ask questions one at a time. Confirm understanding before moving on. Probe if answers are vague.

#### 1a. What topic?

Get the topic in plain language. Examples: "the version bump workflow", "how the project-setup skill initializes a new project", "the choice to use uv instead of pip", "the agent skill system in this repo".

Save as `topic`.

#### 1b. Why now?

Why is this being documented now? Onboarding, a decision review, a future audit, a handoff? This shapes tone and emphasis.

Save as `purpose`.

#### 1c. Audience density levels

Which levels are needed? Pick one or more:

1. Executive
2. Manager
3. Engineering

Save as `levels`.

#### 1d. Known context

Are there specific files, modules, pull requests, or external links the document should reference or be grounded in? Capture all of them.

Save as `seed_references`.

#### 1e. Anything to omit?

Are there sensitive details, internal names, or in-progress decisions that should be left out or fuzzed?

Save as `omit`.

#### 1f. Mermaid diagrams?

Would one or more diagrams help? Common useful diagrams:

- Flowchart for a workflow or decision tree.
- Sequence diagram for interactions between components or actors.
- Component or class diagram for structural relationships.
- State diagram for lifecycles.

If yes, ask what each diagram should show. Save as `diagrams`.

### 2. Research the codebase

Before writing, search the codebase to ground the document in reality. Do not write from assumption.

Use Grep, Glob, and Read to find:

- Files named or related to the topic.
- Configuration that defines the behavior.
- Tests that pin down expected behavior.
- Existing docs or comments that already cover parts of the topic.

Note what you find. If something contradicts the user's mental model, surface it before writing.

### 3. Draft an outline

Before writing the full document, show the user a short outline:

- One-line title and proposed slug.
- For each requested density level, three to six section headings.
- Where any diagrams will appear.

Wait for approval or amendments before drafting the full document.

### 4. Write the document

Write one density level at a time. After each level, run a self-check:

- Re-read the section. Does it sound like a human wrote it?
- Did any em-dashes, ellipsis, smart quotes, emojis, or non-ASCII characters sneak in?
- Are sentences varied in length?
- Is active voice dominant?

Fix anything that fails the check before moving on.

### 5. Add diagrams

Insert Mermaid diagrams where they were planned. Use the neon palette in the next section. Every diagram needs a short caption sentence above or below it.

### 6. Save the file

Write to `docs/topics/YYYYMMDD-<slug>.md`. Create `docs/topics/` if it does not exist.

### 7. Verify and report

Re-read the saved file. Confirm:

- File name follows the date and slug pattern.
- No emojis, em-dashes, ellipsis, smart quotes, or other non-ASCII characters.
- All requested density levels are present and ordered correctly.
- All requested diagrams are present and use the neon palette.

Tell the user the file path and offer to revise specific sections.

## Mermaid Styling: Neon Palette

Every Mermaid diagram uses this palette. It produces high-contrast, neon-themed diagrams that feel fresh and clean.

| Class         | Fill      | Stroke    | Text     | Use for                          |
| ------------- | --------- | --------- | -------- | -------------------------------- |
| `neonCyan`    | `#00E5FF` | `#0097A7` | `#000000`| primary or entry nodes           |
| `neonPink`    | `#FF1493` | `#9C0F5C` | `#FFFFFF`| key decisions or critical nodes  |
| `neonGreen`   | `#39FF14` | `#1A8000` | `#000000`| success states or outputs        |
| `neonPurple`  | `#BF00FF` | `#6B008C` | `#FFFFFF`| processes or transformations     |
| `neonOrange`  | `#FF6E00` | `#A04600` | `#000000`| warnings or conditional branches |
| `neonYellow`  | `#FFFF00` | `#9C9C00` | `#000000`| highlighted or notable nodes     |

Every diagram ends with `classDef` blocks defining the classes used, then `class` blocks applying them to nodes. Aim for two to four colors per diagram. More than that starts to feel chaotic.

### Reference example

```
flowchart LR
    A[Start] --> B{Decision}
    B -->|Yes| C[Action]
    B -->|No| D[Skip]
    C --> E[Done]
    D --> E

    classDef neonCyan fill:#00E5FF,stroke:#0097A7,stroke-width:2px,color:#000000
    classDef neonPink fill:#FF1493,stroke:#9C0F5C,stroke-width:2px,color:#FFFFFF
    classDef neonGreen fill:#39FF14,stroke:#1A8000,stroke-width:2px,color:#000000
    classDef neonPurple fill:#BF00FF,stroke:#6B008C,stroke-width:2px,color:#FFFFFF

    class A neonCyan
    class B neonPink
    class C neonPurple
    class D neonPurple
    class E neonGreen
```

### Diagram readability rules

- Keep node labels short. One to four words. Long labels destroy layout.
- Use `flowchart LR` (left to right) for workflows. Use `flowchart TD` (top down) for hierarchical structures.
- Use `sequenceDiagram` for time-ordered interactions between actors or services.
- Never put more than around a dozen nodes in one diagram. Split into multiple diagrams if needed.
- Captions explain what the diagram shows in one sentence. Do not restate the obvious.

## Document Template

Every output file follows this skeleton. Omit sections for density levels the user did not request.

```
# <Title in sentence case>

One-sentence framing of the topic.

**Date:** YYYY-MM-DD
**Topic:** <topic>
**Purpose:** <one-line purpose from interview>

## Executive

<two to five short paragraphs>

## Manager

<half a page to a full page, with tables where useful>

## Engineering

<one to several pages, conceptual depth, no raw code>

## References

- <file path or external link>
- <file path or external link>
```

The `References` section is required if any specific files, pull requests, or external sources informed the writing. List them as a bulleted list with short descriptions where helpful.

## Common Mistakes

| Mistake                                              | Fix                                                                  |
| ---------------------------------------------------- | -------------------------------------------------------------------- |
| Writing from assumption without searching the code   | Always grep and read first. Ground every claim.                      |
| Including code snippets in the Engineering level     | Describe the concept. Refer to the file by name. Do not paste code.  |
| Using em-dashes or smart quotes                      | Re-read every paragraph. Replace with commas, periods, or hyphens.   |
| Single dense block per density level                 | Split into headed subsections. Use tables and bullets.               |
| Mermaid diagram with default styling                 | Always apply the neon palette `classDef` blocks.                     |
| Slug too long, too vague, or not kebab-case          | 2 to 5 lowercase kebab-case words. "auth-rate-limit-design".         |
| Skipping the outline review                          | Show the outline first. Cheap to amend before drafting.              |
| Writing all three density levels when only one asked | Confirm levels in the interview. Only produce what was requested.    |

## Self-Check Before Reporting Complete

Run this checklist before telling the user the document is ready:

- [ ] File path matches `docs/topics/YYYYMMDD-<slug>.md`.
- [ ] All requested density levels are present and ordered Executive, then Manager, then Engineering.
- [ ] No emojis, em-dashes, en-dashes, ellipsis characters, smart quotes, or other non-ASCII characters anywhere.
- [ ] No raw code blocks in any density level.
- [ ] Any Mermaid diagrams use the neon palette and have captions.
- [ ] References section lists every file or link that informed the writing.
- [ ] Re-reading the document, it sounds like a thoughtful human wrote it.
