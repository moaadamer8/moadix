/*
 * moadix-checker: the only program that reads MOADIX's Keychain secrets.
 *
 * Keychain items (generic passwords, account "operator" unless noted):
 *   moadix-totp        20-byte TOTP secret (RFC 6238, SHA-1, 30 s, 6 digits)
 *   moadix-ledger-key  32-byte HMAC-SHA256 key
 *   moadix-state       "laststep=N fails=N until=T" + MAC   (single use, cooldown)
 *   moadix-anchor      account = product id: "seq hash" + MAC
 *
 * Threat model, measured 2026-11-11 on a file-based keychain:
 *   - READ (decrypt) is enforced: only this binary's cdhash can read an item;
 *     anything else gets errSecAuthFailed (interaction off) or a dialog.
 *   - WRITE and DELETE are NOT enforced while the keychain is unlocked, even
 *     with ACL entries that name only this binary: any same-user process can
 *     delete an item and re-add one with its own value that trusts this binary.
 * Therefore:
 *   - PIN: both secrets are pinned by a hash recorded in a root-owned file
 *     (the managed-settings file). A swapped secret fails the pin: fail closed.
 *   - state and anchor values carry an HMAC under the (pinned) ledger key, so a
 *     planted value is rejected. Their values cannot be read by others, so an
 *     old value cannot be replayed. A deleted item fails closed.
 *   - Wrong codes pause approvals (cooldown): after 3 consecutive wrong codes,
 *     15 minutes, doubling on each further wrong code, capped at 24 hours.
 *     Attempts during a pause are refused unevaluated and never extend it,
 *     so a flood of wrong codes from any caller cannot push it past 24 h.
 *     A valid code after the pause resets the count. No password dialog.
 *
 * A ledger line is produced only by `record`, after a valid unused code in the
 * same invocation. There is no standalone "sign". The checker chooses seq and
 * prev from the anchor; the caller cannot.
 *
 * Build flags: MOADIX_KEYCHAIN="/abs/path" pins a keychain; MOADIX_PINFILE pins
 * the pin file; MOADIX_TEST skips the root-ownership check on the pin file
 * (test fixtures cannot be root-owned without sudo). Nothing at run
 * time (environment, arguments) changes which keychain or pin file is used.
 */
#include <Security/Security.h>
#include <CommonCrypto/CommonHMAC.h>
#include <CommonCrypto/CommonDigest.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <fcntl.h>
#include <unistd.h>
#include <ctype.h>
#include <sys/stat.h>
#include <libgen.h>

#pragma clang diagnostic ignored "-Wdeprecated-declarations"

#define SVC_TOTP "moadix-totp"
#define SVC_KEY "moadix-ledger-key"
#define SVC_STATE "moadix-state"
#define SVC_ANCHOR "moadix-anchor"
#define ACCT "operator"
#define MAX_FAILS 3
#define PAUSE_BASE (15 * 60)
#define PAUSE_CAP (24 * 60 * 60)
#define STEP 30
#ifndef MOADIX_PINFILE
#define MOADIX_PINFILE "/Library/Application Support/ClaudeCode/managed-settings.json"
#endif

static SecKeychainRef g_kc;

/* The production build reads the real clock only. The test build adds
 * MOADIX_TEST_CLOCK_OFFSET seconds so the corpus can step through pauses. */
static long long now_s(void) {
    long long t = (long long)time(NULL);
#ifdef MOADIX_TEST
    const char *o = getenv("MOADIX_TEST_CLOCK_OFFSET");
    if (o) t += atoll(o);
#endif
    return t;
}
static unsigned char g_totp[64], g_key[64];
static UInt32 g_totp_len, g_key_len;

static void wipe(void) { memset(g_totp, 0, sizeof g_totp); memset(g_key, 0, sizeof g_key); }
static void die(int rc, const char *msg) { wipe(); printf("ERR %s\n", msg); exit(rc); }

static void hex(const unsigned char *b, size_t n, char *out) {
    for (size_t i = 0; i < n; i++) sprintf(out + 2 * i, "%02x", b[i]);
    out[2 * n] = 0;
}

static int unhex(const char *s, unsigned char *out, size_t max, size_t *n) {
    size_t l = strlen(s);
    if (l % 2 || l / 2 > max) return 0;
    for (size_t i = 0; i < l / 2; i++) {
        unsigned int v;
        if (!isxdigit((unsigned char)s[2 * i]) || !isxdigit((unsigned char)s[2 * i + 1])) return 0;
        sscanf(s + 2 * i, "%2x", &v); out[i] = (unsigned char)v;
    }
    *n = l / 2; return 1;
}

static void open_kc(void) {
#ifdef MOADIX_KEYCHAIN
    if (SecKeychainOpen(MOADIX_KEYCHAIN, &g_kc) != errSecSuccess) die(10, "keychain-open");
#else
    if (SecKeychainCopyDefault(&g_kc) != errSecSuccess) die(10, "keychain-open");
#endif
}

/* Items get an ACL whose decrypt AND encrypt/delete entries name only this
 * binary. Measured: the keychain enforces the decrypt part only; the rest is
 * kept because it costs nothing and documents intent. */
static OSStatus kc_create(const char *svc, const char *acct, const void *data, UInt32 len) {
    SecTrustedApplicationRef self = NULL;
    OSStatus s = SecTrustedApplicationCreateFromPath(NULL, &self);
    if (s) return s;
    CFArrayRef apps = CFArrayCreate(NULL, (const void **)&self, 1, &kCFTypeArrayCallBacks);
    CFStringRef label = CFStringCreateWithCString(NULL, svc, kCFStringEncodingUTF8);
    SecAccessRef access = NULL;
    s = SecAccessCreate(label, apps, &access);
    if (!s) {
        CFArrayRef acls = NULL;
        s = SecAccessCopyACLList(access, &acls);
        for (CFIndex i = 0; !s && acls && i < CFArrayGetCount(acls); i++) {
            SecACLRef acl = (SecACLRef)CFArrayGetValueAtIndex(acls, i);
            CFArrayRef auths = SecACLCopyAuthorizations(acl);
            int enc = auths && CFArrayContainsValue(auths, CFRangeMake(0, CFArrayGetCount(auths)), kSecACLAuthorizationEncrypt);
            if (auths) CFRelease(auths);
            if (!enc) continue;
            const void *want[] = {kSecACLAuthorizationEncrypt, kSecACLAuthorizationDelete};
            CFArrayRef na = CFArrayCreate(NULL, want, 2, &kCFTypeArrayCallBacks);
            s = SecACLUpdateAuthorizations(acl, na);
            CFRelease(na);
            if (!s) s = SecACLSetContents(acl, apps, label, kSecKeychainPromptRequirePassphase);
        }
        if (acls) CFRelease(acls);
    }
    if (!s) {
        SecKeychainAttribute attrs[] = {
            {kSecServiceItemAttr, (UInt32)strlen(svc), (void *)svc},
            {kSecAccountItemAttr, (UInt32)strlen(acct), (void *)acct},
            {kSecLabelItemAttr, (UInt32)strlen(svc), (void *)svc},
        };
        SecKeychainAttributeList list = {3, attrs};
        s = SecKeychainItemCreateFromContent(kSecGenericPasswordItemClass, &list, len, data, g_kc, access, NULL);
    }
    if (access) CFRelease(access);
    CFRelease(label); CFRelease(apps); CFRelease(self);
    return s;
}

/* On success *out (NUL-terminated, malloc'd) and *outlen are set. */
static OSStatus kc_get(const char *svc, const char *acct, unsigned char **out, UInt32 *outlen) {
    void *data = NULL; UInt32 len = 0;
    OSStatus s = SecKeychainFindGenericPassword(g_kc, (UInt32)strlen(svc), svc, (UInt32)strlen(acct), acct, &len, &data, NULL);
    if (s == errSecSuccess) {
        *out = malloc(len + 1); memcpy(*out, data, len); (*out)[len] = 0; *outlen = len;
        SecKeychainItemFreeContent(NULL, data);
    }
    return s;
}

static OSStatus kc_put(const char *svc, const char *acct, const void *data, UInt32 len) {
    void *old = NULL; UInt32 oldlen = 0; SecKeychainItemRef item = NULL;
    OSStatus s = SecKeychainFindGenericPassword(g_kc, (UInt32)strlen(svc), svc, (UInt32)strlen(acct), acct, &oldlen, &old, &item);
    if (s == errSecSuccess) {
        SecKeychainItemFreeContent(NULL, old);
        s = SecKeychainItemModifyAttributesAndData(item, NULL, len, data);
        CFRelease(item);
        return s;
    }
    if (s != errSecItemNotFound) return s;
    return kc_create(svc, acct, data, len);
}

static void compute_pin(const unsigned char *t, size_t tl, const unsigned char *k, size_t kl, char out[33]) {
    CC_SHA256_CTX c; unsigned char d[32];
    CC_SHA256_Init(&c);
    CC_SHA256_Update(&c, "moadix-pin-v1", 13);
    CC_SHA256_Update(&c, t, (CC_LONG)tl);
    CC_SHA256_Update(&c, k, (CC_LONG)kl);
    CC_SHA256_Final(d, &c);
    hex(d, 16, out);
}

/* Reads "MOADIX_PIN": "<32 hex>" from the pin file. In production the file
 * and its directory must be root-owned and not group/world-writable. */
static int read_pin(char out[33]) {
    const char *path = MOADIX_PINFILE;
#ifndef MOADIX_TEST
    struct stat st; char dir[1024];
    if (stat(path, &st) || st.st_uid != 0 || (st.st_mode & 022)) return 0;
    strncpy(dir, path, sizeof dir - 1); dir[sizeof dir - 1] = 0;
    if (stat(dirname(dir), &st) || st.st_uid != 0 || (st.st_mode & 022)) return 0;
#endif
    FILE *f = fopen(path, "r"); if (!f) return 0;
    static char buf[262144]; size_t n = fread(buf, 1, sizeof buf - 1, f); fclose(f); buf[n] = 0;
    char *p = strstr(buf, "\"MOADIX_PIN\""); if (!p) return 0;
    p = strchr(p + 12, ':'); if (!p) return 0;
    p = strchr(p, '"'); if (!p) return 0; p++;
    for (int i = 0; i < 32; i++) if (!isxdigit((unsigned char)p[i])) return 0;
    if (p[32] != '"') return 0;
    memcpy(out, p, 32); out[32] = 0;
    for (int i = 0; i < 32; i++) out[i] = (char)tolower((unsigned char)out[i]);
    return 1;
}

static void load_secrets(void) {
    unsigned char *t = NULL, *k = NULL; UInt32 tl = 0, kl = 0;
    if (kc_get(SVC_TOTP, ACCT, &t, &tl) != errSecSuccess) die(13, "totp-secret-unreadable");
    if (kc_get(SVC_KEY, ACCT, &k, &kl) != errSecSuccess) { memset(t, 0, tl); free(t); die(13, "ledger-key-unreadable"); }
    if (tl > sizeof g_totp || kl > sizeof g_key || tl < 16 || kl < 32) die(13, "secret-size");
    memcpy(g_totp, t, tl); g_totp_len = tl; memcpy(g_key, k, kl); g_key_len = kl;
    memset(t, 0, tl); free(t); memset(k, 0, kl); free(k);
    char want[33], have[33];
    if (!read_pin(want)) die(14, "pin-missing");
    compute_pin(g_totp, g_totp_len, g_key, g_key_len, have);
    if (strcmp(want, have)) die(15, "pin-mismatch");
}

static void mac_hex(const char *domain, const char *acct, const char *val, char out[65]) {
    CCHmacContext c; unsigned char m[32];
    CCHmacInit(&c, kCCHmacAlgSHA256, g_key, g_key_len);
    CCHmacUpdate(&c, domain, strlen(domain)); CCHmacUpdate(&c, "|", 1);
    CCHmacUpdate(&c, acct, strlen(acct)); CCHmacUpdate(&c, "|", 1);
    CCHmacUpdate(&c, val, strlen(val));
    CCHmacFinal(&c, m); hex(m, 32, out);
}

/* MAC'd values: "<value>|<hmac>". Returns 1 ok, 0 not found, dies on tamper. */
static int get_macd(const char *svc, const char *acct, char *val, size_t vmax) {
    unsigned char *d = NULL; UInt32 l = 0;
    OSStatus s = kc_get(svc, acct, &d, &l);
    if (s == errSecItemNotFound) return 0;
    if (s) die(16, "item-unreadable");
    char *bar = strrchr((char *)d, '|'); char want[65];
    if (!bar || strlen(bar + 1) != 64) die(17, "item-tampered");
    *bar = 0; mac_hex(svc, acct, (char *)d, want);
    int diff = 0; for (int i = 0; i < 64; i++) diff |= want[i] ^ bar[1 + i];
    if (diff || strlen((char *)d) >= vmax) die(17, "item-tampered");
    strcpy(val, (char *)d); free(d);
    return 1;
}

static void put_macd(const char *svc, const char *acct, const char *val) {
    char m[65], buf[512]; mac_hex(svc, acct, val, m);
    snprintf(buf, sizeof buf, "%s|%s", val, m);
    if (kc_put(svc, acct, buf, (UInt32)strlen(buf))) die(18, "item-write");
}

typedef struct { long long laststep; int fails; long long until; } State;

static State load_state(void) {
    State st = {0, 0, 0}; char v[256];
    if (!get_macd(SVC_STATE, ACCT, v, sizeof v)) die(11, "state-missing");
    if (sscanf(v, "laststep=%lld fails=%d until=%lld", &st.laststep, &st.fails, &st.until) != 3) die(11, "state-corrupt");
    return st;
}

static void save_state(State st) {
    char v[128]; snprintf(v, sizeof v, "laststep=%lld fails=%d until=%lld", st.laststep, st.fails, st.until);
    put_macd(SVC_STATE, ACCT, v);
}

static long long hotp(long long counter) {
    unsigned char msg[8], mac[CC_SHA1_DIGEST_LENGTH];
    for (int i = 7; i >= 0; i--) { msg[i] = counter & 0xff; counter >>= 8; }
    CCHmac(kCCHmacAlgSHA1, g_totp, g_totp_len, msg, 8, mac);
    int off = mac[19] & 0x0f;
    long long bin = ((long long)(mac[off] & 0x7f) << 24) | (mac[off + 1] << 16) | (mac[off + 2] << 8) | mac[off + 3];
    return bin % 1000000;
}

static int valid_code_str(const char *c) {
    if (!c || strlen(c) != 6) return 0;
    for (int i = 0; i < 6; i++) if (!isdigit((unsigned char)c[i])) return 0;
    return 1;
}

/* 0 = no match, -1 = matched an already-used step, else the matched step.
 * Accepts the previous, current and next 30 s step (clock skew). */
static long long match_code(const char *code, long long laststep) {
    long long want = atoll(code), now = now_s() / STEP, used = 0;
    for (int d = -1; d <= 1; d++) {
        long long step = now + d;
        if (hotp(step) == want) { if (step > laststep) return step; used = -1; }
    }
    return used;
}

static int safe_id(const char *s) {
    if (!s || !*s || strlen(s) > 64) return 0;
    for (; *s; s++) if (!(isalnum((unsigned char)*s) || *s == '-' || *s == '_' || *s == '.')) return 0;
    return 1;
}

static int safe_text(const char *s, size_t max) { /* printable ASCII without " and \ */
    if (!s || !*s || strlen(s) > max) return 0;
    for (; *s; s++) if (*s < 0x20 || *s > 0x7e || *s == '"' || *s == '\\') return 0;
    return 1;
}

static int safe_b64(const char *s) {
    if (!s || strlen(s) > 16384) return 0;
    for (; *s; s++) if (!(isalnum((unsigned char)*s) || *s == '+' || *s == '/' || *s == '=')) return 0;
    return 1;
}

static void base32(const unsigned char *in, size_t n, char *out) {
    const char *a = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"; unsigned int buf = 0; int bits = 0; size_t o = 0;
    for (size_t i = 0; i < n; i++) {
        buf = (buf << 8) | in[i]; bits += 8;
        while (bits >= 5) { out[o++] = a[(buf >> (bits - 5)) & 31]; bits -= 5; }
    }
    if (bits) out[o++] = a[(buf << (5 - bits)) & 31];
    out[o] = 0;
}

static const char *arg(int argc, char **argv, const char *name) {
    for (int i = 2; i + 1 < argc; i++) if (!strcmp(argv[i], name)) return argv[i + 1];
    return NULL;
}

/* ---------------------------------------------------------------- commands */

static int cmd_init(void) {
    unsigned char *x = NULL; UInt32 l = 0;
    OSStatus a = kc_get(SVC_TOTP, ACCT, &x, &l), b = kc_get(SVC_KEY, ACCT, &x, &l);
    if (a != errSecItemNotFound || b != errSecItemNotFound) die(20, "already-initialised");
    if (SecRandomCopyBytes(kSecRandomDefault, 20, g_totp) || SecRandomCopyBytes(kSecRandomDefault, 32, g_key)) die(21, "rng");
    g_totp_len = 20; g_key_len = 32;
    if (kc_put(SVC_TOTP, ACCT, g_totp, 20) || kc_put(SVC_KEY, ACCT, g_key, 32)) die(22, "keychain-write");
    State st = {0, 0, 0}; save_state(st);
    char b32[64], uri[256], pin[33];
    base32(g_totp, 20, b32);
    snprintf(uri, sizeof uri, "otpauth://totp/MOADIX:operator?secret=%s&issuer=MOADIX&algorithm=SHA1&digits=6&period=30", b32);
    compute_pin(g_totp, 20, g_key, 32, pin);
    /* Printed once, to the installer (which renders the QR code). A later
     * delete-and-re-init by anyone else yields secrets that fail the
     * root-owned pin, so this output is only useful at install time. */
    printf("OK uri=%s pin=%s\n", uri, pin);
    memset(b32, 0, sizeof b32); memset(uri, 0, sizeof uri); wipe();
    return 0;
}

static int cmd_record(int argc, char **argv) {
    const char *product = arg(argc, argv, "--product"), *action = arg(argc, argv, "--action"),
               *code = arg(argc, argv, "--code"), *payload = arg(argc, argv, "--payload-b64");
    if (!payload) payload = "";
    if (!safe_id(product) || !safe_text(action, 512) || !valid_code_str(code) || !safe_b64(payload))
        die(30, "bad-arguments");
    load_secrets();
    State st = load_state();
    long long t = now_s();
    if (t < st.until) { printf("ERR paused %lld\n", st.until - t); wipe(); exit(31); }
    long long step = match_code(code, st.laststep);
    if (step == -1) die(32, "code-already-used");
    if (step == 0) {
        st.fails++;
        if (st.fails >= MAX_FAILS) {
            long long pause = PAUSE_BASE;
            for (int i = MAX_FAILS; i < st.fails && pause < PAUSE_CAP; i++) pause *= 2;
            if (pause > PAUSE_CAP) pause = PAUSE_CAP;
            st.until = t + pause; save_state(st);
            printf("ERR wrong-code-paused %lld\n", pause); wipe(); exit(33);
        }
        save_state(st);
        die(33, "wrong-code");
    }
    st.laststep = step; st.fails = 0; st.until = 0; save_state(st);

    char av[256]; long long seq = 0; char prev[65] = "GENESIS";
    if (get_macd(SVC_ANCHOR, product, av, sizeof av) && sscanf(av, "%lld %64s", &seq, prev) != 2) die(34, "anchor-corrupt");

    char ts[32]; time_t now = (time_t)now_s(); struct tm g; gmtime_r(&now, &g); strftime(ts, sizeof ts, "%Y-%m-%dT%H:%M:%SZ", &g);
    size_t blen = strlen(action) + strlen(payload) + 512;
    char *body = malloc(blen);
    snprintf(body, blen, "{\"seq\":%lld,\"prev\":\"%s\",\"ts\":\"%s\",\"product\":\"%s\",\"action\":\"%s\",\"payload_b64\":\"%s\"}",
             seq + 1, prev, ts, product, action, payload);
    unsigned char h[32], m[32]; char hh[65], mh[65];
    CC_SHA256(body, (CC_LONG)strlen(body), h); hex(h, 32, hh);
    CCHmac(kCCHmacAlgSHA256, g_key, g_key_len, body, strlen(body), m); hex(m, 32, mh);
    char anchor[128]; snprintf(anchor, sizeof anchor, "%lld %s", seq + 1, hh);
    put_macd(SVC_ANCHOR, product, anchor);
    printf("{\"body\":\"");
    for (char *p = body; *p; p++) { if (*p == '"') putchar('\\'); putchar(*p); }
    printf("\",\"hash\":\"%s\",\"hmac\":\"%s\"}\n", hh, mh);
    free(body); wipe();
    return 0;
}

/* Spend any 6-digit token the operator sent that did not become a recorded
 * action, so a valid code that reaches the agent's context is already used.
 * Output never says whether the code was valid; never counts as a failure. */
static int cmd_burn(int argc, char **argv) {
    const char *code = arg(argc, argv, "--code");
    if (valid_code_str(code)) {
        load_secrets();
        State st = load_state();
        long long step = match_code(code, st.laststep);
        if (step > 0) { st.laststep = step; save_state(st); }
    }
    wipe(); printf("OK\n");
    return 0;
}

/* stdin: lines "<body_hex> <hmac_hex>"; stdout: "ok" or "bad" per line. */
static int cmd_verify(void) {
    load_secrets();
    static char line[70000]; static unsigned char body[35000];
    while (fgets(line, sizeof line, stdin)) {
        char *sp = strchr(line, ' '); size_t bn = 0, wn = 0; unsigned char want[64];
        if (!sp) { puts("bad"); continue; }
        *sp = 0; char *mh = sp + 1; mh[strcspn(mh, "\r\n")] = 0;
        if (!unhex(line, body, sizeof body, &bn) || !unhex(mh, want, sizeof want, &wn) || wn != 32) { puts("bad"); continue; }
        unsigned char m[32]; CCHmac(kCCHmacAlgSHA256, g_key, g_key_len, body, bn, m);
        int diff = 0; for (int i = 0; i < 32; i++) diff |= m[i] ^ want[i];
        puts(diff ? "bad" : "ok");
    }
    wipe(); return 0;
}

static int cmd_anchor(int argc, char **argv) {
    const char *product = arg(argc, argv, "--product");
    if (!safe_id(product)) die(50, "bad-arguments");
    load_secrets();
    char v[256];
    if (!get_macd(SVC_ANCHOR, product, v, sizeof v)) printf("OK 0 GENESIS\n");
    else printf("OK %s\n", v);
    wipe(); return 0;
}

static int cmd_state(void) {
    load_secrets();
    State st = load_state();
    long long t = now_s(), left = st.until > t ? st.until - t : 0;
    wipe(); printf("OK fails=%d paused_for=%lld\n", st.fails, left); return 0;
}

int main(int argc, char **argv) {
    setvbuf(stdout, NULL, _IOLBF, 0);
    if (argc < 2) die(2, "usage: init|record|burn|verify|anchor|state");
    SecKeychainSetUserInteractionAllowed(false);
    open_kc();
    const char *c = argv[1];
    if (!strcmp(c, "init")) return cmd_init();
    if (!strcmp(c, "record")) return cmd_record(argc, argv);
    if (!strcmp(c, "burn")) return cmd_burn(argc, argv);
    if (!strcmp(c, "verify")) return cmd_verify();
    if (!strcmp(c, "anchor")) return cmd_anchor(argc, argv);
    if (!strcmp(c, "state")) return cmd_state();
    die(2, "unknown-command");
    return 2;
}
