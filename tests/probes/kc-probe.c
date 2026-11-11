/* Attack probe: a process that is NOT the checker asks the Keychain for the
 * TOTP secret. argv[1] = keychain path, argv[2] = "nointeract" | "interact". */
#include <Security/Security.h>
#include <stdio.h>
#include <string.h>
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
int main(int argc, char **argv) {
    if (argc < 3) return 2;
    SecKeychainSetUserInteractionAllowed(strcmp(argv[2], "interact") == 0);
    SecKeychainRef kc; if (SecKeychainOpen(argv[1], &kc)) return 3;
    UInt32 len = 0; void *data = NULL;
    OSStatus s = SecKeychainFindGenericPassword(kc, 11, "moadix-totp", 8, "operator", &len, &data, NULL);
    CFStringRef m = SecCopyErrorMessageString(s, NULL); char buf[256] = "";
    if (m) CFStringGetCString(m, buf, sizeof buf, kCFStringEncodingUTF8);
    printf("status=%d (%s) secret_bytes_returned=%u\n", (int)s, buf, data ? len : 0);
    return s == 0 ? 0 : 1;
}
