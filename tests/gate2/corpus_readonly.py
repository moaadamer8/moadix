"""The classifier corpus (DESIGN.md section 7: "command classifier rewritten
against a fixture corpus of read-only commands").

READ_ONLY: commands that v1 or the interim classifier wrongly denied, grouped by
the six false-positive classes the user listed, plus neighbours of each. Every
one must get NO objection from the gate inside a product at phase 1.

MUST_DENY: the write-side neighbours of the same shapes, so a classifier that
"fixes" a false positive by ignoring the class is caught.

Placeholders: {scratch} = a git repo outside the product (a scratch copy),
{product} = the product root.
"""

READ_ONLY = [
    # 1. git stash list (and the other read-only stash/apply forms)
    ("stash", "git stash list"),
    ("stash", "git stash list --date=relative"),
    ("stash", "git stash show -p stash@{0}"),
    ("stash", "git status && git log --oneline -5 && git stash list"),
    ("stash", "git apply --check fix.patch"),
    ("stash", "git reset HEAD sdlc/01-research.md"),
    ("stash", "git clean -n"),
    # 2. a *.pem / *.key pattern in a read-only find
    ("pem", "find . -name '*.pem'"),
    ("pem", "find . -name \"*.pem\" -print"),
    ("pem", "find . -name '*.pem' -exec ls -l {} \\;"),
    ("pem", "find . -name '*.key' -exec openssl rsa -in {} -check -noout \\;"),
    ("pem", "find . -name '*.pem' | xargs ls -l"),
    ("pem", "find . -name '*.pem' -exec grep -l BEGIN {} +"),
    # 3. a bare "."
    ("dot", "ls ."),
    ("dot", "grep -rn TODO ."),
    ("dot", "du -sh ."),
    ("dot", "find . -type f | wc -l"),
    ("dot", "cd . && ls"),
    ("dot", "test -d . && echo yes"),
    ("dot", "git add ."),
    ("dot", "cp sdlc/01-research.md {scratch}/"),
    # 4. tar -C
    ("tar", "tar -C sdlc -czf {scratch}/sdlc.tgz ."),
    ("tar", "tar -czf {scratch}/docs.tgz -C docs ."),
    ("tar", "tar -tzf {scratch}/sdlc.tgz"),
    ("tar", "tar -xzf {scratch}/sdlc.tgz -C {scratch}/unpacked"),
    ("tar", "tar czf {scratch}/all.tgz -C . sdlc"),
    # 5. git checkout in a scratch copy
    ("checkout", "cd {scratch} && git checkout -q HEAD~1"),
    ("checkout", "git -C {scratch} checkout -q main"),
    ("checkout", "git -C {scratch} reset --hard HEAD"),
    ("checkout", "cd {scratch} && git stash && git stash pop"),
    ("checkout", "git checkout -b feature/x"),
    ("checkout", "git checkout -- sdlc/01-research.md"),
    # 6. cd sweeps
    ("cd", "cd {scratch} && touch notes.txt; cd {product} && git status"),
    ("cd", "cd sdlc && ls && cd .. && cd docs && ls"),
    ("cd", "for d in sdlc docs; do (cd $d && ls); done"),
    ("cd", "(cd {scratch} && echo hi > out.txt) && git status"),
    ("cd", "pushd {scratch} && echo x > a.txt && popd && ls"),
    ("cd", "cd {scratch} && mkdir -p build && cd - && git log -1"),
    ("cd", "cd sdlc && echo draft > 01-notes.md"),
]

MUST_DENY = [
    ("stash", "git stash"),
    ("stash", "git stash pop"),
    ("stash", "git reset --hard HEAD~1"),
    ("stash", "git clean -fd"),
    ("pem", "find . -name '*.pem' -exec rm {} \\;"),
    ("pem", "find . -name '*.pem' -delete"),
    ("pem", "find . -name '*.pem' | xargs rm"),
    ("dot", "cp {scratch}/evil.md ."),
    ("dot", "touch ."),
    ("dot", "rm -rf ."),
    ("tar", "tar -xzf {scratch}/sdlc.tgz"),
    ("tar", "tar -xzf {scratch}/sdlc.tgz -C .sdlc"),
    ("tar", "tar -czf .sdlc/x.tgz sdlc"),
    ("checkout", "git checkout -q HEAD~1"),
    ("checkout", "git -C {product} checkout main"),
    ("checkout", "cd {scratch} && cd {product} && git checkout HEAD~1"),
    ("checkout", "git checkout HEAD~1 -- .sdlc"),
    ("cd", "cd .sdlc && echo x >> ledger.jsonl"),
    ("cd", "cd {scratch} && cd {product}/.sdlc && rm ledger.jsonl"),
    ("cd", "(cd .sdlc; echo x > phase.yaml)"),
    ("cd", "cd \"$DIR\" && echo x > out.txt"),
    ("cd", "cd {scratch} && cd - && echo x > src/a.ts"),
    ("cd", "pushd sdlc && popd && echo x > src/a.ts"),
]
