// Command launcher runs a vendored tool (unpacked AppImage or single binary) without a shell.
//
// It is installed as /usr/bin/<tool>, and as /usr/bin/env for `#!/usr/bin/env X` scripts
// (exiftool), since the image has no coreutils. The name it is run under picks the tool's prefix, whose
// launch.json says what to exec and with which environment; the AppImages' own AppRun scripts
// need bash, which the image does not have.
package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"syscall"
)

// tools maps the name the launcher is run under to the prefix its files were unpacked into.
var tools = map[string]string{
	"darktable-cli":   "/opt/darktable",
	"rawtherapee-cli": "/opt/rawtherapee",
	"yt-dlp":          "/opt/yt-dlp",
}

// recipe is <prefix>/launch.json. Paths are relative to the prefix; values in env and
// env_default may use ${PREFIX}.
type recipe struct {
	Exec        string            `json:"exec"`
	Loader      string            `json:"loader"`
	LibraryPath []string          `json:"library_path"`
	Env         map[string]string `json:"env"`
	EnvDefault  map[string]string `json:"env_default"`
}

func main() { os.Exit(launch(os.Args, tools, os.Environ(), os.Stderr)) }

// launch execs the tool named by argv[0]; it returns only on failure, with the exit code.
func launch(argv []string, tools map[string]string, environ []string, stderr io.Writer) int {
	name := filepath.Base(argv[0])
	if name == "env" {
		return runEnv(argv[1:], environ, stderr)
	}
	prefix, ok := tools[name]
	if !ok {
		fmt.Fprintf(stderr, "launcher: no tool for %s\n", name)
		return 127
	}
	r, err := readRecipe(filepath.Join(prefix, "launch.json"))
	if err != nil {
		fmt.Fprintf(stderr, "launcher: %s: %v\n", name, err)
		return 127
	}
	path, args, env := r.command(prefix, argv[1:], environ)
	err = syscall.Exec(path, args, env)
	fmt.Fprintf(stderr, "launcher: %s: exec %s: %v\n", name, path, err)
	return 126
}

// runEnv is a minimal env(1): NAME=VALUE assignments, then a command looked up on PATH
// (or used as-is if it contains a slash). No options.
func runEnv(args, environ []string, stderr io.Writer) int {
	env := newEnv(environ)
	for len(args) > 0 {
		a := args[0]
		if strings.HasPrefix(a, "-") {
			fmt.Fprintf(stderr, "env: options are not supported: %s\n", a)
			return 125
		}
		k, v, ok := strings.Cut(a, "=")
		if !ok {
			break
		}
		env.set(k, v)
		args = args[1:]
	}
	if len(args) == 0 {
		fmt.Fprintln(stderr, "usage: env [NAME=VALUE]... COMMAND [ARG]...")
		return 125
	}
	path := lookPath(args[0], env.values["PATH"])
	if path == "" {
		fmt.Fprintf(stderr, "env: %s: not found\n", args[0])
		return 127
	}
	err := syscall.Exec(path, args, env.list())
	fmt.Fprintf(stderr, "env: %s: %v\n", args[0], err)
	return 126
}

// lookPath finds cmd as execvp does: as-is if it contains a slash, else in each PATH dir.
func lookPath(cmd, pathList string) string {
	if strings.Contains(cmd, "/") {
		if isExecutable(cmd) {
			return cmd
		}
		return ""
	}
	for _, dir := range filepath.SplitList(pathList) {
		if dir == "" {
			dir = "."
		}
		if p := filepath.Join(dir, cmd); isExecutable(p) {
			return p
		}
	}
	return ""
}

func isExecutable(p string) bool {
	fi, err := os.Stat(p)
	return err == nil && fi.Mode().IsRegular() && fi.Mode().Perm()&0o111 != 0
}

func readRecipe(file string) (*recipe, error) {
	data, err := os.ReadFile(file)
	if err != nil {
		return nil, err
	}
	dec := json.NewDecoder(bytes.NewReader(data))
	dec.DisallowUnknownFields()
	var r recipe
	if err := dec.Decode(&r); err != nil {
		return nil, fmt.Errorf("%s: %w", file, err)
	}
	if r.Exec == "" {
		return nil, fmt.Errorf("%s: no exec", file)
	}
	return &r, nil
}

// command returns the path, argv and environment to exec.
func (r *recipe) command(prefix string, args, environ []string) (string, []string, []string) {
	env := newEnv(environ)
	for _, k := range sortedKeys(r.Env) {
		env.set(k, strings.ReplaceAll(r.Env[k], "${PREFIX}", prefix))
	}
	for _, k := range sortedKeys(r.EnvDefault) {
		if !env.has(k) {
			env.set(k, strings.ReplaceAll(r.EnvDefault[k], "${PREFIX}", prefix))
		}
	}
	dirs := make([]string, len(r.LibraryPath))
	for i, d := range r.LibraryPath {
		dirs[i] = filepath.Join(prefix, d)
	}
	libraryPath := strings.Join(dirs, ":")
	exe := filepath.Join(prefix, r.Exec)

	if r.Loader != "" {
		loader := filepath.Join(prefix, r.Loader)
		argv := append([]string{loader, "--library-path", libraryPath, exe}, args...)
		return loader, argv, env.list()
	}
	if len(dirs) > 0 {
		env.set("LD_LIBRARY_PATH", libraryPath)
	}
	return exe, append([]string{exe}, args...), env.list()
}

// env is an environment that keeps the caller's order; later sets replace earlier values.
type env struct {
	keys   []string
	values map[string]string
}

func newEnv(environ []string) *env {
	e := &env{values: map[string]string{}}
	for _, kv := range environ {
		k, v, _ := strings.Cut(kv, "=")
		e.set(k, v)
	}
	return e
}

func (e *env) has(k string) bool { _, ok := e.values[k]; return ok }

func (e *env) set(k, v string) {
	if !e.has(k) {
		e.keys = append(e.keys, k)
	}
	e.values[k] = v
}

func (e *env) list() []string {
	out := make([]string, len(e.keys))
	for i, k := range e.keys {
		out[i] = k + "=" + e.values[k]
	}
	return out
}

func sortedKeys(m map[string]string) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}
