// SPDX-License-Identifier: GPL-2.0-only
#include <errno.h>
#include <fcntl.h>
#include <pwd.h>
#include <security/pam_appl.h>
#include <security/pam_modules.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

static const char data_key[] = "t2touch-action-prompt";
static const char touchid_conf_path[] = "/etc/t2-touchid.conf";
static const char touchid_user_key[] = "T2_TOUCHID_USER=";
static const char nerd_font_path[] =
    "/usr/share/fonts/TTF/JetBrainsMonoNerdFont-Regular.ttf";
static const char action_prompt[] =
    "Place your finger on the fingerprint reader";
static const char nerd_action_prompt[] =
    "󰈷 Place your finger on the fingerprint reader";
static const char fallback_action_prompt[] =
    "◎ Place your finger on the fingerprint reader";

struct prompt_context {
    struct pam_conv upstream;
    struct pam_conv replacement;
    /*
     * sudo now shows this prompt through the Touch ID dashboard instead
     * (notify_dms_scan_started() below); showing it again as terminal
     * text would be redundant. Polkit has no equivalent dashboard wiring
     * yet, so it keeps the existing marked, rewritten text.
     */
    int suppress_for_sudo;
    /* One-shot: avoids re-forking a relay process on every retry once the
     * password prompt has already been seen once in this transaction. */
    int password_fallback_notified;
};

/* Defined below, alongside notify_dms_scan_started(); forward-declared so
 * marked_conversation() can call it when sudo falls back to a password. */
static void notify_dms_password_fallback(void);

static int marked_conversation(int count, const struct pam_message **messages,
                               struct pam_response **responses, void *data)
{
    struct prompt_context *context = data;
    struct pam_message *rewritten;
    const struct pam_message **forwarded;
    const char *marked_prompt;
    int result;
    int index;

    if (count <= 0 || messages == NULL || responses == NULL || context == NULL ||
        context->upstream.conv == NULL)
        return PAM_CONV_ERR;

    if (messages[0] != NULL && count == 1 && context->suppress_for_sudo &&
        messages[0]->msg_style == PAM_TEXT_INFO &&
        messages[0]->msg != NULL &&
        strcmp(messages[0]->msg, action_prompt) == 0) {
        struct pam_response *silent_response = calloc(1, sizeof(*silent_response));

        if (silent_response == NULL)
            return PAM_BUF_ERR;
        *responses = silent_response;
        return PAM_SUCCESS;
    }

    rewritten = calloc((size_t)count, sizeof(*rewritten));
    forwarded = calloc((size_t)count, sizeof(*forwarded));
    if (rewritten == NULL || forwarded == NULL) {
        free(rewritten);
        free(forwarded);
        return PAM_BUF_ERR;
    }
    marked_prompt = access(nerd_font_path, R_OK) == 0
                        ? nerd_action_prompt
                        : fallback_action_prompt;

    for (index = 0; index < count; index++) {
        if (messages[index] == NULL) {
            free(forwarded);
            free(rewritten);
            return PAM_CONV_ERR;
        }
        rewritten[index] = *messages[index];
        if (rewritten[index].msg_style == PAM_TEXT_INFO &&
            rewritten[index].msg != NULL &&
            strcmp(rewritten[index].msg, action_prompt) == 0)
            rewritten[index].msg = marked_prompt;
        if (context->suppress_for_sudo && !context->password_fallback_notified &&
            rewritten[index].msg_style == PAM_PROMPT_ECHO_OFF) {
            /*
             * This is the real password prompt (pam_unix, via system-auth),
             * reached after pam_fprintd gives up. Nothing else ever tells
             * the dashboard fingerprint is no longer in play for this sudo
             * attempt, so it would otherwise sit frozen on its last
             * scanning/failure frame through however the password goes.
             */
            context->password_fallback_notified = 1;
            notify_dms_password_fallback();
        }
        forwarded[index] = &rewritten[index];
    }

    result = context->upstream.conv(count, forwarded, responses,
                                    context->upstream.appdata_ptr);
    free(forwarded);
    free(rewritten);
    return result;
}

static void free_prompt_context(pam_handle_t *pamh, void *data, int status)
{
    struct prompt_context *context = data;
    const void *current = NULL;

    (void)status;
    if (pamh != NULL && context != NULL &&
        pam_get_item(pamh, PAM_CONV, &current) == PAM_SUCCESS &&
        current != NULL) {
        const struct pam_conv *live = (const struct pam_conv *)current;

        /* pam_set_item copies the conv; match by wrapper and appdata. */
        if (live->conv == marked_conversation && live->appdata_ptr == context)
            (void)pam_set_item(pamh, PAM_CONV, &context->upstream);
    }
    free(context);
}

static int valid_touchid_username_char(char character)
{
    return (character >= 'A' && character <= 'Z') ||
           (character >= 'a' && character <= 'z') ||
           (character >= '0' && character <= '9') || character == '_' ||
           character == '.' || character == '-';
}

/*
 * Extract T2_TOUCHID_USER's value from /etc/t2-touchid.conf, matching the
 * charset other T2Touch scripts (t2-pam-unlock.sh) validate against. A
 * later duplicate line wins, matching this repo's `tail -n 1` convention
 * for that file. Returns 0 and a NUL-terminated value in `out` on success.
 */
static int read_touchid_user(char *out, size_t out_size)
{
    FILE *file;
    char line[256];
    int found = 0;

    if (out_size == 0)
        return -1;
    file = fopen(touchid_conf_path, "r");
    if (file == NULL)
        return -1;
    while (fgets(line, sizeof(line), file) != NULL) {
        size_t key_len = strlen(touchid_user_key);
        size_t line_len = strlen(line);
        size_t value_len;
        size_t index;

        if (strncmp(line, touchid_user_key, key_len) != 0)
            continue;
        while (line_len > 0 &&
               (line[line_len - 1] == '\n' || line[line_len - 1] == '\r'))
            line[--line_len] = '\0';
        if (line_len <= key_len)
            continue;
        value_len = line_len - key_len;
        if (value_len >= out_size)
            continue;
        for (index = 0; index < value_len; index++) {
            if (!valid_touchid_username_char(line[key_len + index])) {
                value_len = 0;
                break;
            }
        }
        if (value_len == 0)
            continue;
        memcpy(out, line + key_len, value_len);
        out[value_len] = '\0';
        found = 1;
    }
    fclose(file);
    return found ? 0 : -1;
}

/*
 * Resolve and validate /run/user/<uid> the same way the fprintd backend's
 * desktop_user_unit_command() does: it must exist, be owned by that uid,
 * and grant no group/other access, or there is no live session to notify.
 */
static int touchid_runtime_dir(uid_t uid, char *out_path, size_t out_size)
{
    struct stat info;

    if ((size_t)snprintf(out_path, out_size, "/run/user/%ld", (long)uid) >=
        out_size)
        return -1;
    if (lstat(out_path, &info) != 0)
        return -1;
    if (!S_ISDIR(info.st_mode) || info.st_uid != uid ||
        (info.st_mode & 0077) != 0)
        return -1;
    return 0;
}

/*
 * Tell the configured desktop user's DMS shell that a fingerprint scan for
 * sudo has started, via its "touchid" IPC target. Best-effort and
 * non-blocking: sudo's actual authentication decision never depends on
 * this. Uses a double fork so the dashboard-relay process is reparented to
 * init rather than requiring this PAM module to wait for it or touch the
 * process-wide SIGCHLD disposition sudo itself relies on for the command
 * it will later run.
 */
/*
 * Fire `dms ipc call touchid <event> [event_arg]` as the configured
 * desktop user, as a best-effort, non-blocking relay. Used both to show
 * the dashboard when a scan starts and to hide it once sudo falls back to
 * a plain password (see marked_conversation()) -- fingerprint is no
 * longer in play at that point, and nothing else would ever tell the
 * dashboard to go away.
 */
static void relay_touchid_event(const char *event, const char *event_arg)
{
    char username[64];
    char runtime_dir[64];
    char runtime_dir_env[80];
    struct passwd *account;
    uid_t target_uid;
    gid_t target_gid;
    pid_t relay_launcher;

    if (read_touchid_user(username, sizeof(username)) != 0)
        return;
    account = getpwnam(username);
    if (account == NULL || account->pw_uid == 0)
        return;
    target_uid = account->pw_uid;
    target_gid = account->pw_gid;
    if (touchid_runtime_dir(target_uid, runtime_dir,
                            sizeof(runtime_dir)) != 0)
        return;
    if ((size_t)snprintf(runtime_dir_env, sizeof(runtime_dir_env),
                         "XDG_RUNTIME_DIR=%s", runtime_dir) >=
        sizeof(runtime_dir_env))
        return;

    relay_launcher = fork();
    if (relay_launcher < 0)
        return;
    if (relay_launcher == 0) {
        pid_t relay = fork();

        if (relay == 0) {
            int devnull;

            setsid();
            devnull = open("/dev/null", O_RDWR);
            if (devnull >= 0) {
                dup2(devnull, STDIN_FILENO);
                dup2(devnull, STDOUT_FILENO);
                dup2(devnull, STDERR_FILENO);
                if (devnull > STDERR_FILENO)
                    close(devnull);
            }
            /*
             * sudo drops its real uid to the invoking user for the PAM
             * conversation phase, keeping only the effective uid at 0 as
             * a defense-in-depth measure against exactly this kind of
             * module action. `runuser`/`su` refuse to run under that
             * combination (they check the real uid), so drop privileges
             * to the target account directly instead, the same way any
             * privileged daemon would.
             */
            if (setgid(target_gid) != 0)
                _exit(127);
            if (setuid(target_uid) != 0)
                _exit(127);
            if (getuid() != target_uid || geteuid() != target_uid)
                _exit(127);
            if (event_arg != NULL) {
                char *const relay_argv[] = {
                    (char *)"/usr/bin/env",
                    runtime_dir_env,
                    (char *)"/usr/bin/dms",
                    (char *)"ipc",
                    (char *)"call",
                    (char *)"touchid",
                    (char *)event,
                    (char *)event_arg,
                    NULL
                };
                execv(relay_argv[0], relay_argv);
            } else {
                char *const relay_argv[] = {
                    (char *)"/usr/bin/env",
                    runtime_dir_env,
                    (char *)"/usr/bin/dms",
                    (char *)"ipc",
                    (char *)"call",
                    (char *)"touchid",
                    (char *)event,
                    NULL
                };
                execv(relay_argv[0], relay_argv);
            }
            _exit(127);
        }
        /* The launcher's only job was handing the relay to init; it does
         * not wait, so a stuck/slow relay can never block authentication. */
        _exit(0);
    }
    {
        int status;

        while (waitpid(relay_launcher, &status, 0) < 0 && errno == EINTR)
            continue;
    }
}

static void notify_dms_scan_started(void)
{
    relay_touchid_event("show", "sudo");
}

static void notify_dms_password_fallback(void)
{
    relay_touchid_event("hide", NULL);
}

PAM_EXTERN int pam_sm_authenticate(pam_handle_t *pamh, int flags, int argc,
                                   const char **argv)
{
    const struct pam_conv *upstream;
    const void *existing;
    const void *service_name;
    struct prompt_context *context;
    int result;

    (void)flags;
    (void)argc;
    (void)argv;

    notify_dms_scan_started();

    if (pam_get_data(pamh, data_key, &existing) == PAM_SUCCESS)
        return PAM_IGNORE;
    if (pam_get_item(pamh, PAM_CONV, (const void **)&upstream) != PAM_SUCCESS ||
        upstream == NULL || upstream->conv == NULL)
        return PAM_IGNORE;

    context = calloc(1, sizeof(*context));
    if (context == NULL)
        return PAM_IGNORE;
    context->upstream = *upstream;
    context->replacement.conv = marked_conversation;
    context->replacement.appdata_ptr = context;
    service_name = NULL;
    context->suppress_for_sudo =
        pam_get_item(pamh, PAM_SERVICE, &service_name) == PAM_SUCCESS &&
        service_name != NULL &&
        strcmp((const char *)service_name, "sudo") == 0;

    result = pam_set_data(pamh, data_key, context, free_prompt_context);
    if (result != PAM_SUCCESS) {
        free(context);
        return PAM_IGNORE;
    }
    (void)pam_set_item(pamh, PAM_CONV, &context->replacement);
    return PAM_IGNORE;
}

PAM_EXTERN int pam_sm_setcred(pam_handle_t *pamh, int flags, int argc,
                              const char **argv)
{
    (void)pamh;
    (void)flags;
    (void)argc;
    (void)argv;
    return PAM_IGNORE;
}
