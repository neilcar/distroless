// Command launcher runs a vendored tool (unpacked AppImage or single binary) without a shell.
//
// It is installed as /usr/bin/<tool>. The name it is run under picks the tool's prefix, whose
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
