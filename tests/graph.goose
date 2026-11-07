// SPDX-License-Identifier: Apache-2.0
import task from "../vendor/goose-task";
import watch from "../vendor/goose-watch";
import glob from "../vendor/goose-glob";
import crypto from "../vendor/goose-crypto";
import http from "../vendor/goose-http";
import honk_metadata from "../vendor/honk-metadata";
import process from "../vendor/goose-process";
import semver from "../vendor/goose-semver";
import text from "../vendor/goose-text";
import toml_edit from "../vendor/goose-toml-edit";
import toml from "../vendor/goose-toml";
import argparse from "../vendor/goose-argparse";
import logger from "../vendor/goose-log";
import time from "../vendor/goose-time";
import utc from "../vendor/goose-log/examples/utc";
import posix from "../vendor/goose-terminal";
import honk from "..";
import std;
fn main() {
    var g = deps::Graph { .. };
    assert(deps::graph_error(g).kind == task::ErrorKind.None);
    for i in 256 { g.nodes.push(deps::Node { name: str("node", i), .. }); }
    // Full node boundary and >65536 duplicate edges are accepted.
    for i in deps::MAX_GRAPH_EDGES { g.edges.push(deps::Edge { 0, 255 }); }
    assert(deps::graph_error(g).kind == task::ErrorKind.None);
    for node, i in g.nodes { assert(node.name == str("node", i)); }
    assert(g.edges.len == deps::MAX_GRAPH_EDGES);
    g.edges.push(deps::Edge { 0, 255 });
    assert(deps::graph_error(g).kind == task::ErrorKind.EdgeLimit);
    g.edges.clear(); g.edges.push(deps::Edge { 0, 256 });
    let invalid = deps::graph_error(g);
    assert(invalid.kind == task::ErrorKind.InvalidTask && invalid.edge == 0 && invalid.task == 256);
    g.edges.clear(); g.edges.push(deps::Edge { 0, 0 });
    assert(deps::graph_error(g).kind == task::ErrorKind.Cycle);
    g.edges.clear();
    for i in 255 { g.edges.push(deps::Edge { i, i + 1 }); }
    assert(deps::graph_error(g).kind == task::ErrorKind.None);
    g.edges.push(deps::Edge { 255, 0 });
    assert(deps::graph_error(g).kind == task::ErrorKind.Cycle);
    g.edges.clear(); g.edges.push(deps::Edge { 0, 1 });
    // FIFO plan starts [0, 2, 3, ...] but node/lock order stays [0, 1, 2, ...].
    assert(deps::graph_error(g).kind == task::ErrorKind.None);
    for node, i in g.nodes { assert(node.name == str("node", i)); }
    g.nodes.push(deps::Node { .. });
    assert(deps::graph_error(g).kind == task::ErrorKind.TaskLimit);
    print("dependency graph contracts passed");
}
