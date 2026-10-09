# 0013. Web Push with VAPID, and an in-app notification centre as the fallback

- Status: accepted
- Date: 2026-10-09

## Context

A reminder is only useful if it reaches the phone when the app is closed. The app is an installable PWA with no native code, no paid service and no account with a third party.

## Decision

- **Web Push** through the browser's own push service. The browser gives us a subscription (an endpoint URL and two keys); we store it in `push_subscriptions`, one row per device. A message is encrypted and sent to the endpoint by `pywebpush`, signed with our **VAPID** key pair. A service worker (`/sw.js`, served from the site root) shows the notification and opens `/notifications` when it is tapped. It caches nothing.
- **The keys are configuration.** `uv run python -m glucobalance.push` prints a new pair for `GBA_VAPID_PRIVATE_KEY` and `GBA_VAPID_PUBLIC_KEY`. Only the public key is ever sent to the browser. Without keys the app works as before and the reminders page says phone notifications are not set up.
- **The notification centre is the source of truth.** A `Notification` row is saved for every fired reminder (and committed) before a push is attempted. The nav shows an unread count, `/notifications` lists them, and push is only a way to tell the phone about a row that already exists. Browsers without push, iPhones where the app is not on the Home Screen, and blocked permissions all still see the reminder in the app.
- **Delivery never raises.** A 404 or 410 from the push service means the user revoked the subscription, so it is deleted. Any other failure is logged (without the endpoint, which is a private address) and the subscription is kept.
- **A subscription belongs to one user.** Subscribing the same endpoint as another user moves it, so a shared browser does not receive the previous person's reminders.
- **Subscribe endpoints take JSON.** With the lax same-site session cookie, a form on another site cannot make the browser send this request.
- The payload carries only the reminder's title and a short generic sentence, never a glucose value, because lock screens show it.

## Consequences

- Delivery is tested with a fake sender and a patched `webpush`; a real phone needs HTTPS and cannot be tested in CI. The "Send a test" button on the reminders page checks the whole path by hand.
- Push is best effort: the push service can delay or drop a message. The reminder still waits in the notification centre.
- Browser vendors' push services see that a message was sent, not its content.

## Alternatives considered

- **Native app or Firebase Cloud Messaging:** needs an app store or a Google project; Web Push is standard and free.
- **Email or SMS:** costs money or reveals more, and is slower.
- **Polling from the page:** does not work when the app is closed.
