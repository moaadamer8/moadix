/* Attack probe: a process that is NOT the checker asks the Keychain for the
 * TOTP secret. argv[1] = keychain path, argv[2] = "nointeract" | "interact".
 * argv[2] = "status": health probe for the corpus. Reports the keychain's lock
 * state and whether the moadix-totp item exists, WITHOUT asking for its data
 * (an attribute-only lookup needs no ACL decision). */
#include <Security/Security.h>
#include <stdio.h>
#include <string.h>
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
static void msg(OSStatus s, char *buf, size_t n) {
    CFStringRef m = SecCopyErrorMessageString(s, NULL); buf[0] = 0;
    if (m) { CFStringGetCString(m, buf, (CFIndex)n, kCFStringEncodingUTF8); CFRelease(m); }
}
static int status_probe(const char *path) {
    SecKeychainSetUserInteractionAllowed(false);
    SecKeychainRef kc; char b[256];
    OSStatus s = SecKeychainOpen(path, &kc);
    if (s) { msg(s, b, sizeof b); printf("open=%d (%s)\n", (int)s, b); return 1; }
    SecKeychainStatus st = 0;
    s = SecKeychainGetStatus(kc, &st);
    msg(s, b, sizeof b);
    printf("get_status=%d (%s) unlocked=%d readable=%d writable=%d", (int)s, b,
           !!(st & kSecUnlockStateStatus), !!(st & kSecReadPermStatus), !!(st & kSecWritePermStatus));
    SecKeychainItemRef item = NULL;
    s = SecKeychainFindGenericPassword(kc, 11, "moadix-totp", 8, "operator", NULL, NULL, &item);
    msg(s, b, sizeof b);
    printf(" totp_item=%d (%s)\n", (int)s, b);
    if (item) CFRelease(item);
    return 0;
}
int main(int argc, char **argv) {
    if (argc < 3) return 2;
    if (strcmp(argv[2], "status") == 0) return status_probe(argv[1]);
    SecKeychainSetUserInteractionAllowed(strcmp(argv[2], "interact") == 0);
    SecKeychainRef kc; if (SecKeychainOpen(argv[1], &kc)) return 3;
    UInt32 len = 0; void *data = NULL;
    OSStatus s = SecKeychainFindGenericPassword(kc, 11, "moadix-totp", 8, "operator", &len, &data, NULL);
    CFStringRef m = SecCopyErrorMessageString(s, NULL); char buf[256] = "";
    if (m) CFStringGetCString(m, buf, sizeof buf, kCFStringEncodingUTF8);
    printf("status=%d (%s) secret_bytes_returned=%u\n", (int)s, buf, data ? len : 0);
    return s == 0 ? 0 : 1;
}
