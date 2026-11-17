"""Independent exhaustive SAT oracle for small acyclic registry graphs."""
import itertools
import json
import random


def version(text):
    return tuple(map(int, text.split('.')))


def family(text):
    major, minor, patch = version(text)
    return (major,) if major else ((0, minor) if minor else (0, 0, patch))


def matches(requirement, text):
    actual = version(text)
    for clause in requirement.split(','):
        clause = clause.strip()
        operator = next(op for op in ('>=', '<=', '=', '^') if clause.startswith(op))
        expected = version(clause[len(operator):])
        if operator == '=' and actual != expected:
            return False
        if operator == '>=' and actual < expected:
            return False
        if operator == '<=' and actual > expected:
            return False
        if operator == '^':
            major, minor, patch = expected
            upper = (major + 1, 0, 0) if major else ((0, minor + 1, 0) if minor else (0, 0, patch + 1))
            if not expected <= actual < upper:
                return False
    return True


def satisfiable(records, roots):
    # Enumerate release subsets, independently of the production backtracker.
    # Generated dependencies only point forward, so every closed subset is acyclic.
    releases = list(records)
    for bits in itertools.product((False, True), repeat=len(releases)):
        selected = [r for r, keep in zip(releases, bits) if keep]
        groups = [(name, family(ver)) for name, ver in selected]
        if len(groups) != len(set(groups)):
            continue
        requirements = list(roots)
        for release in selected:
            requirements.extend((package, req) for _, package, req in records[release])
        if all(any(name == package and matches(req, ver) for name, ver in selected)
               for package, req in requirements):
            return True
    return False


def check(fixture, samples=64):
    rng = random.Random(0xC4A60)
    fixture.package('app', 'fn main() {}')
    manifest = fixture.root / 'app/Honk.toml'
    initial = manifest.read_text()
    counts = {True: 0, False: 0}
    for sample in range(samples):
        versions = [('1.0.0', '1.1.0', '2.0.0'),
                    ('0.1.0', '0.1.1', '0.2.0'),
                    ('0.0.1', '0.0.2', '0.1.0')][sample % 3]
        names = [f'oracle-{sample}-p{i}' for i in range(3)]
        choices = ['=' + v for v in versions] + ['^' + versions[0], f'>={versions[0]},<={versions[-1]}']
        records, hashes = {}, {}
        for i, name in enumerate(names):
            for ver in versions:
                deps = [(f'd{j}', names[j], rng.choice(choices))
                        for j in range(i + 1, len(names)) if rng.random() < 0.45]
                records[name, ver] = deps
                published = fixture.registry_release(name, ver, deps=deps)
                hashes[published['sha256']] = name, ver
        roots = [(rng.choice(names), rng.choice(choices)) for _ in range(rng.randint(1, 3))]
        if sample % 4 == 0:
            roots = [(names[0], "=" + versions[0]), (names[0], "=" + versions[1])]
        expected = satisfiable(records, roots)
        counts[expected] += 1
        manifest.write_text(initial)
        for i, (name, requirement) in enumerate(roots):
            fixture.registry_dependency('app', f'root{i}', name, requirement)
        lock = fixture.root / 'app/Honk.lock'
        previous = lock.read_bytes() if lock.exists() else None
        before = len(fixture.registry.requests)
        result = fixture.run_honk('fetch', ok=expected)
        if not expected:
            fixture.assertIn('no compatible scoped registry graph', result.stderr, (sample, roots))
            fixture.assertEqual(lock.read_bytes() if lock.exists() else None, previous)
            fixture.assertFalse(any(path.endswith('.tar.gz') for path, _ in fixture.registry.requests[before:]))
            continue
        graph = json.loads((fixture.root / 'app/target/isolated/graph.json').read_text())
        nodes = {node['key']: node for node in graph['nodes']}
        releases = {node['key']: hashes[node['source']['revision'][7:]]
                    for node in graph['nodes'] if node['key'] != graph['root']}
        groups = [(name, family(ver)) for name, ver in releases.values()]
        fixture.assertEqual(len(groups), len(set(groups)), (sample, releases))
        root = nodes[graph['root']]
        for i, (name, req) in enumerate(roots):
            chosen_name, chosen_version = releases[root['bindings'][f'root{i}']]
            fixture.assertEqual(chosen_name, name)
            fixture.assertTrue(matches(req, chosen_version), (sample, roots, releases))
        for key, release in releases.items():
            fixture.assertEqual(set(nodes[key]['bindings']), {alias for alias, _, _ in records[release]})
            for alias, name, req in records[release]:
                chosen_name, chosen_version = releases[nodes[key]['bindings'][alias]]
                fixture.assertEqual(chosen_name, name)
                fixture.assertTrue(matches(req, chosen_version), (sample, release, alias))
        reached = {graph['root']}
        for _ in nodes:
            reached |= {target for key in tuple(reached) for target in nodes[key]['bindings'].values()}
        fixture.assertEqual(reached, set(nodes), (sample, 'unreachable stale resolution nodes'))
    fixture.assertGreater(counts[True], 0)
    fixture.assertGreater(counts[False], 0)
    print(f"registry oracle: {samples} graphs ({counts[True]} SAT, {counts[False]} UNSAT)")
    return counts
