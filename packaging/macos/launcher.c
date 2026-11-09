/*
 * FREQUENZ launcher for macOS.
 *
 * The bundle's main executable. It points the process at the libraries and data
 * inside FREQUENZ.app, then hands over to the bundled Python interpreter. All
 * paths are derived from the executable's own location, so the app can be moved
 * from dist/ to /Applications or mounted from the .dmg.
 */

#include <limits.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#ifndef PYTHON_VERSION
#define PYTHON_VERSION "3.15"
#endif

static void join(char *out, size_t size, const char *base, const char *suffix) {
    snprintf(out, size, "%s%s", base, suffix);
}

static void prepend_env(const char *name, const char *value) {
    const char *current = getenv(name);
    char combined[PATH_MAX * 2];
    if (current != NULL && current[0] != '\0') {
        snprintf(combined, sizeof combined, "%s:%s", value, current);
        setenv(name, combined, 1);
    } else {
        setenv(name, value, 1);
    }
}

int main(int argc, char **argv) {
    char exe[PATH_MAX];
    uint32_t size = sizeof exe;
    if (_NSGetExecutablePath(exe, &size) != 0) {
        return 1;
    }

    char macos[PATH_MAX];
    if (realpath(exe, macos) == NULL) {
        return 1;
    }
    char *slash = strrchr(macos, '/');
    if (slash == NULL) {
        return 1;
    }
    *slash = '\0'; /* Contents/MacOS */

    char contents[PATH_MAX], resources[PATH_MAX], frameworks[PATH_MAX];
    char python_home[PATH_MAX], python_bin[PATH_MAX], cache[PATH_MAX];
    char path[PATH_MAX], schemas[PATH_MAX], typelibs[PATH_MAX], plugins[PATH_MAX];
    char scanner[PATH_MAX], pixbuf[PATH_MAX], registry[PATH_MAX], gio_modules[PATH_MAX];

    join(contents, sizeof contents, macos, "/..");
    join(resources, sizeof resources, contents, "/Resources");
    join(frameworks, sizeof frameworks, contents, "/Frameworks");
    snprintf(python_home, sizeof python_home, "%s/Python.framework/Versions/%s", frameworks, PYTHON_VERSION);
    join(python_bin, sizeof python_bin, macos, "/frequenz-bin");
    join(schemas, sizeof schemas, resources, "/share/glib-2.0/schemas");
    join(typelibs, sizeof typelibs, resources, "/girepository-1.0");
    join(plugins, sizeof plugins, resources, "/gstreamer-1.0");
    join(scanner, sizeof scanner, macos, "/gst-plugin-scanner");
    join(pixbuf, sizeof pixbuf, resources, "/gdk-pixbuf-2.0/loaders");
    join(gio_modules, sizeof gio_modules, resources, "/gio/modules");
    join(path, sizeof path, resources, "/share");

    const char *home = getenv("HOME");
    if (home == NULL) {
        home = "/tmp";
    }
    snprintf(cache, sizeof cache, "%s/Library/Caches/frequenz", home);
    mkdir(cache, 0700);
    snprintf(registry, sizeof registry, "%s/gstreamer-1.0-%s.bin", cache, PYTHON_VERSION);

    setenv("PYTHONHOME", python_home, 1);
    setenv("PYTHONDONTWRITEBYTECODE", "1", 1);
    setenv("PYTHONUTF8", "1", 1);
    setenv("FREQUENZ_BUNDLE_RESOURCES", resources, 1);
    setenv("GI_TYPELIB_PATH", typelibs, 1);
    setenv("GSETTINGS_SCHEMA_DIR", schemas, 1);
    setenv("GDK_PIXBUF_MODULEDIR", pixbuf, 1);
    setenv("GIO_MODULE_DIR", gio_modules, 1);
    setenv("GST_PLUGIN_SYSTEM_PATH_1_0", plugins, 1);
    setenv("GST_PLUGIN_PATH_1_0", plugins, 1);
    setenv("GST_PLUGIN_SCANNER", scanner, 1);
    setenv("GST_REGISTRY_1_0", registry, 1);
    setenv("GST_REGISTRY_UPDATE", "yes", 1);
    prepend_env("XDG_DATA_DIRS", path);
    prepend_env("DYLD_FALLBACK_LIBRARY_PATH", frameworks);

    /* python -m frequenzradio [arguments...] */
    char **args = calloc((size_t) argc + 4, sizeof(char *));
    if (args == NULL) {
        return 1;
    }
    args[0] = python_bin;
    args[1] = "-m";
    args[2] = "frequenzradio";
    for (int i = 1; i < argc; i++) {
        args[i + 2] = argv[i];
    }
    args[argc + 2] = NULL;

    execv(python_bin, args);
    perror("frequenz: could not start the bundled Python");
    return 1;
}
