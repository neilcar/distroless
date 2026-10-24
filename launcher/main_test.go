package main

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// The test binary doubles as the launcher and as the stub it launches, chosen by the name it
// is run under (the launcher itself picks its tool the same way).
const testTool = "testtool"

func TestMain(m *testing.M) {
	switch filepath.Base(os.Args[0]) {
	case "stub", "perl-stub":
		// Print what we were started with, one item per line, so tests can compare exactly.
		for _, a := range os.Args {
			fmt.Println("arg=" + a)
		}
		ld, ok := os.LookupEnv("LD_LIBRARY_PATH")
		fmt.Printf("LD_LIBRARY_PATH=%s set=%t\n", ld, ok)
		fmt.Println("HOME=" + os.Getenv("HOME"))
		fmt.Println("TOOL_DATA=" + os.Getenv("TOOL_DATA"))
		os.Exit(0)
	case "env":
		os.Exit(launch(os.Args, nil, os.Environ(), os.Stderr))
	case testTool, "unknown-tool":
		os.Exit(launch(os.Args, map[string]string{testTool: os.Getenv("LAUNCHER_TEST_PREFIX")},
			os.Environ(), os.Stderr))
	}
	os.Exit(m.Run())
}

// setup makes a prefix holding the stub and launch.json, and a link named `name` to the
// test binary; it returns the prefix and the link.
func setup(t *testing.T, recipe map[string]any, name string) (string, string) {
	t.Helper()
	self, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	prefix := t.TempDir()
	if err := os.MkdirAll(filepath.Join(prefix, "usr/bin"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(self, filepath.Join(prefix, "usr/bin/stub")); err != nil {
		t.Fatal(err)
	}
	data, err := json.Marshal(recipe)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(prefix, "launch.json"), data, 0o644); err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(t.TempDir(), name)
	if err := os.Symlink(self, link); err != nil {
		t.Fatal(err)
	}
	return prefix, link
}

func run(t *testing.T, link, prefix string, env []string, args ...string) (stdout, stderr string, code int) {
	t.Helper()
	cmd := exec.Command(link, args...)
	cmd.Env = append([]string{"LAUNCHER_TEST_PREFIX=" + prefix}, env...)
	var out, errb strings.Builder
	cmd.Stdout, cmd.Stderr = &out, &errb
	err := cmd.Run()
	if exit, ok := err.(*exec.ExitError); ok {
		return out.String(), errb.String(), exit.ExitCode()
	} else if err != nil {
		t.Fatal(err)
	}
	return out.String(), errb.String(), 0
}

func args(stdout string) []string {
	var got []string
	for _, line := range strings.Split(stdout, "\n") {
		if a, ok := strings.CutPrefix(line, "arg="); ok {
			got = append(got, a)
		}
	}
	return got
}

func equal(a, b []string) bool {
	return strings.Join(a, "\x00") == strings.Join(b, "\x00")
}

func TestLauncherExecsWithLibraryPath(t *testing.T) {
	prefix, link := setup(t, map[string]any{
		"exec":         "usr/bin/stub",
		"library_path": []string{"usr/lib", "usr/lib/extra"},
		"env":          map[string]string{"TOOL_DATA": "${PREFIX}/usr/share"},
		"env_default":  map[string]string{"HOME": "/tmp"},
	}, testTool)
	out, errs, code := run(t, link, prefix, nil, "--version", "two words", "")
	if code != 0 {
		t.Fatalf("exit %d, stderr %q", code, errs)
	}
	want := []string{filepath.Join(prefix, "usr/bin/stub"), "--version", "two words", ""}
	if got := args(out); !equal(got, want) {
		t.Errorf("args = %q, want %q", got, want)
	}
	ld := filepath.Join(prefix, "usr/lib") + ":" + filepath.Join(prefix, "usr/lib/extra")
	for _, line := range []string{"LD_LIBRARY_PATH=" + ld + " set=true", "HOME=/tmp",
		"TOOL_DATA=" + prefix + "/usr/share"} {
		if !strings.Contains(out, line+"\n") {
			t.Errorf("output lacks %q:\n%s", line, out)
		}
	}
}

func TestLauncherUsesLoader(t *testing.T) {
	// The stub stands in for ld.so: it shows the argv the loader would get.
	prefix, link := setup(t, map[string]any{
		"exec":         "usr/bin/real",
		"loader":       "usr/bin/stub",
		"library_path": []string{"usr/lib", "lib"},
	}, testTool)
	out, errs, code := run(t, link, prefix, []string{"LD_LIBRARY_PATH=/caller"}, "-v", "a b")
	if code != 0 {
		t.Fatalf("exit %d, stderr %q", code, errs)
	}
	want := []string{filepath.Join(prefix, "usr/bin/stub"), "--library-path",
		filepath.Join(prefix, "usr/lib") + ":" + filepath.Join(prefix, "lib"),
		filepath.Join(prefix, "usr/bin/real"), "-v", "a b"}
	if got := args(out); !equal(got, want) {
		t.Errorf("args = %q, want %q", got, want)
	}
	if !strings.Contains(out, "LD_LIBRARY_PATH=/caller set=true\n") {
		t.Errorf("caller's LD_LIBRARY_PATH should be left alone with a loader:\n%s", out)
	}
}

func TestLauncherKeepsCallerEnv(t *testing.T) {
	prefix, link := setup(t, map[string]any{
		"exec":        "usr/bin/stub",
		"env_default": map[string]string{"HOME": "/tmp"},
	}, testTool)
	out, errs, code := run(t, link, prefix, []string{"HOME=/x"})
	if code != 0 {
		t.Fatalf("exit %d, stderr %q", code, errs)
	}
	if !strings.Contains(out, "HOME=/x\n") {
		t.Errorf("caller HOME lost:\n%s", out)
	}
	if !strings.Contains(out, "LD_LIBRARY_PATH= set=false\n") {
		t.Errorf("LD_LIBRARY_PATH set with no library_path:\n%s", out)
	}
}

func TestLauncherUnknownName(t *testing.T) {
	prefix, link := setup(t, map[string]any{"exec": "usr/bin/stub"}, "unknown-tool")
	out, errs, code := run(t, link, prefix, nil)
	if code != 127 {
		t.Errorf("exit %d, want 127", code)
	}
	if errs != "launcher: no tool for unknown-tool\n" {
		t.Errorf("stderr = %q", errs)
	}
	if out != "" {
		t.Errorf("stdout = %q", out)
	}
}

// setupEnv returns a link named env to the test binary and a PATH dir holding perl-stub.
func setupEnv(t *testing.T) (envLink, binDir string) {
	t.Helper()
	self, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	binDir = t.TempDir()
	if err := os.Symlink(self, filepath.Join(binDir, "perl-stub")); err != nil {
		t.Fatal(err)
	}
	envLink = filepath.Join(t.TempDir(), "env")
	if err := os.Symlink(self, envLink); err != nil {
		t.Fatal(err)
	}
	return envLink, binDir
}

func TestEnvPassesArgvThroughExactly(t *testing.T) {
	envLink, bin := setupEnv(t)
	out, errs, code := run(t, envLink, "", []string{"PATH=/nonexistent:" + bin}, "perl-stub", "a", "b")
	if code != 0 {
		t.Fatalf("exit %d, stderr %q", code, errs)
	}
	if got, want := args(out), []string{"perl-stub", "a", "b"}; !equal(got, want) {
		t.Errorf("args = %q, want %q", got, want)
	}
}

func TestEnvAppliesAssignments(t *testing.T) {
	envLink, bin := setupEnv(t)
	out, errs, code := run(t, envLink, "", []string{"PATH=" + bin, "HOME=/caller"},
		"HOME=/assigned", "TOOL_DATA=x=y", "perl-stub", "two words")
	if code != 0 {
		t.Fatalf("exit %d, stderr %q", code, errs)
	}
	for _, line := range []string{"HOME=/assigned", "TOOL_DATA=x=y", "arg=two words"} {
		if !strings.Contains(out, line+"\n") {
			t.Errorf("output lacks %q:\n%s", line, out)
		}
	}
}

func TestEnvCommandWithSlashIsUsedAsIs(t *testing.T) {
	envLink, bin := setupEnv(t)
	stub := filepath.Join(bin, "perl-stub")
	out, errs, code := run(t, envLink, "", []string{"PATH=/nonexistent"}, stub, "-x")
	if code != 0 {
		t.Fatalf("exit %d, stderr %q", code, errs)
	}
	if got, want := args(out), []string{stub, "-x"}; !equal(got, want) {
		t.Errorf("args = %q, want %q", got, want)
	}
}

func TestEnvRejectsOptions(t *testing.T) {
	envLink, bin := setupEnv(t)
	for _, argv := range [][]string{{"-i", "perl-stub"}, {"A=1", "-u", "HOME", "perl-stub"}, {"--", "perl-stub"}} {
		out, errs, code := run(t, envLink, "", []string{"PATH=" + bin}, argv...)
		var opt string
		for _, a := range argv {
			if strings.HasPrefix(a, "-") {
				opt = a
				break
			}
		}
		if code != 125 || errs != "env: options are not supported: "+opt+"\n" || out != "" {
			t.Errorf("%q: exit %d, stderr %q, stdout %q", argv, code, errs, out)
		}
	}
}

func TestEnvWithoutCommand(t *testing.T) {
	envLink, _ := setupEnv(t)
	for _, argv := range [][]string{nil, {"A=1"}} {
		out, errs, code := run(t, envLink, "", nil, argv...)
		if code != 125 || !strings.HasPrefix(errs, "usage: env ") || out != "" {
			t.Errorf("%q: exit %d, stderr %q, stdout %q", argv, code, errs, out)
		}
	}
}

func TestEnvMissingCommand(t *testing.T) {
	envLink, bin := setupEnv(t)
	for _, cmd := range []string{"no-such-tool", filepath.Join(bin, "no-such-tool")} {
		_, errs, code := run(t, envLink, "", []string{"PATH=" + bin}, cmd)
		if code != 127 || errs != "env: "+cmd+": not found\n" {
			t.Errorf("%s: exit %d, stderr %q", cmd, code, errs)
		}
	}
}
