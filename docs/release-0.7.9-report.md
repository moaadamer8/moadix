# 0.7.9: unique names per step, and every built image labelled

**Source.** In the product run on 0.7.8, Schemathesis was UNKNOWN in every run: `docker network create failed: network with name moadix-<id>-build already exists`. No moadix network existed before or after the run. The product declares `build.network: registry`, and its compose file builds more than one service. `check_exec.start_live` created the build network once for each built service, always under the name `moadix-<id>-build`, and the engine refused the second one. The 0.7.8 engine run also left two unlabelled `<none>` images.

**Why the engine suite missed it.** smoke-076 already used `build.network: registry`, but it built only one service, so the second build never ran. The suite also listed the images it built without `-a`, so it could not see untagged images.

## The fix

`gate/confined.py`:
- **`Run.unique(base)`** gives every network, volume and container a name that no earlier step of the run used. The first use keeps the old name, and later uses get `-2`, `-3`. The names go through it in `volume`, `network`, `proxy`, `execute`, and the containers that `load` and `copy_out` create.
- **`Run.end_step(containers, networks, volumes)`** removes what one step created, in this order: containers, then networks, then volumes. It removes only names this run created. `close()` still removes everything that carries the run's label, on every exit path.
- **`label_stages(text, run_id)`** adds `LABEL moadix.owner=gate moadix.run=<id>` straight after every `FROM`. It keeps continuations and the `escape` directive, and it refuses a file with no `FROM`. Every image that the classic builder keeps inherits the label. That covers the image of each step and the last image of each earlier stage, all untagged. `docker build --label` labels only the final image.
- A classic (registry) build also gets `--rm --force-rm`. Its step containers then go even when the build fails, so its network can be removed.

`gate/v1/check_exec.py`:
- **Each built service is its own step.** It gets its own build network, egress network, proxy and proxy volume. All of them are removed when its build ends, including when it fails.
- **The install step** removes its proxy, its two networks, its proxy volume and its lockfile volumes when it ends.
- **The build context** carries the stage-labelled Dockerfile. If the Dockerfile is not inside the context, the gate refuses the run.

## Tests

- **`tests/rel079`: new, 22 checks.** With 0.7.8's `confined.py` and `check_exec.py` restored, the fix checks fail and two groups crash.
  - **Controls:** the 0.7.8 gate is UNKNOWN with the product's exact message, and 0.7.8's `--label`-only classic build leaves unlabelled untagged images.
  - **Steps:** each build has its own objects, and its network is removed before the next build starts.
  - **Live gates:** all four pass with two registry builds.
  - **Labels:** every image the double's classic builder keeps carries the run's label.
- **The engine double** behaves more like the engine:
  - it refuses a second network with a name already in use, and refuses to remove a network that a container is still on;
  - it records the images a build keeps (classic: one per step and per stage; BuildKit: the final one), with their labels;
  - it answers `image ls [-a]`.
- **`tests/fixtures/smoke-076`** now builds two services under `build.network: registry`: `app`, and `worker` from the two-stage `Dockerfile.worker`. Every live run on the real engine therefore makes two classic builds, in rel076 (Schemathesis, axe), rel077 (lhci) and rel078 (all four).
- **`tests/confined-engine`:**
  - new group rel079: for each live gate, a pass, no "already exists", nothing of the run left, and every image the run added (`image ls -a`, ids only) labelled with its run id;
  - `built_images` now lists with `-a`, so the final cleanup check counts untagged images;
  - the total is 67.
- **Earlier suites.** `rel076` now expects three proxies (install, plus one per built service). `inc7d`, `rel075`, `rel076`, `rel077` and `rel078` check the new total.

**Not run here.** The real-engine suite, because the sandbox cannot reach Docker.
