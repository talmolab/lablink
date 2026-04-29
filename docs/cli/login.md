# Sign in with `lablink login`

`lablink login` authenticates you to AWS via **AWS Identity Center** (formerly AWS SSO). You sign in once with a username, password, and MFA code in your browser — no IAM access keys, no `aws configure` ever required.

If you've been using LabLink with `aws configure` and access keys, that path still works as a fallback (env vars and `~/.aws/credentials` are honored). But Identity Center is the recommended setup for new users — it's safer (short-lived tokens, no long-lived secrets on disk) and easier (no need to find your access keys in the IAM console).

## TL;DR

```bash
lablink login    # first-time: ~5 min guided bootstrap
                 # subsequent: ~10 sec browser sign-in
```

After login, every other `lablink ...` command (`setup`, `deploy`, `doctor`, etc.) transparently uses the cached SSO credentials.

## Before you start

For your **first** `lablink login`, log into the AWS Console **as your root user** (or an admin IAM user) before running the command. The bootstrap flow opens browser tabs that take you to the AWS Console — if you're already logged in there, those tabs land you on the right page; otherwise they show the AWS sign-in screen mid-flow.

```text
1. Open https://console.aws.amazon.com in your browser.
2. Sign in as the root user of the AWS account where you'll deploy LabLink.
3. Then run `lablink login` in your terminal.
```

After bootstrap, you never need to log into the AWS Console again — all subsequent operations sign in via the Identity Center user, not the root user.

## First-time bootstrap

`lablink login` detects that no `[sso-session lablink]` block exists in `~/.aws/config` and walks you through enabling Identity Center. The flow is fully resumable — if you Ctrl-C between steps, re-running picks up where you left off.

### Step 1 — Enable Identity Center

The CLI opens the Identity Center landing page in your browser. There:

1. Click **Enable**. If asked, choose **account instance** (recommended for personal accounts).
2. Wait ~30 seconds for AWS to provision your Identity Center instance.
3. In the left sidebar, click **Users → Add user**.
4. Fill in your name and email, submit, and check your email for the **Accept invitation** link.
5. Set your password and scan the MFA QR code with an authenticator app (Authy, Google Authenticator, 1Password, etc.).

When you're done, return to the Identity Center dashboard and copy the **SSO Start URL** from the **AWS access portal URLs** section. It looks like `https://d-XXXXXXXXXX.awsapps.com/start`.

Paste that URL back into the CLI when prompted, along with the AWS region your Identity Center is hosted in (visible in the Identity Center dashboard's URL bar — e.g., `us-east-1.console.aws.amazon.com/...`).

!!! warning "Region matters"
    The SSO region (where Identity Center lives) doesn't have to match your deployment region (where LabLink runs). But the CLI's `sso_region` config must match where Identity Center actually lives or `aws sso login` will fail with "InvalidRequestException: RegisterClient".

### Step 2 — Create the LabLink permission set

The CLI opens the Identity Center console again and copies the LabLink policy JSON to your clipboard. There:

1. In the left sidebar, find **Permission sets**. (In newer consoles it's nested under **Multi-account permissions** — expand that first.)
2. Click **Create permission set**.
3. Choose **Custom permission set** and click **Next**.
4. Under **AWS managed policies**, attach:
    - `AmazonEC2FullAccess`
    - `ElasticLoadBalancingFullAccess`
    - `AmazonRoute53FullAccess`
    - `IAMFullAccess`
    - `CloudWatchFullAccess`
    - `CloudWatchLogsFullAccess`
    - `AWSCloudTrail_FullAccess`
    - `AmazonSNSFullAccess`
5. Expand **Custom inline policy**, paste from clipboard (`Cmd-V` / `Ctrl-V`), then click **Next**.
6. Name it `lablink` and click **Next → Create**.

The new permission set will show **Not provisioned** until you assign it in the next step. That's expected.

### Step 3 — Assign your user

Back in the Identity Center console:

1. In the left sidebar, find **AWS accounts** (under **Multi-account permissions** if nested).
2. Check the box next to your AWS account.
3. Click **Assign users or groups**.
4. On the **Users** tab, select your user and click **Next**.
5. Select the `lablink` permission set and click **Next**.
6. Click **Submit**.

After this completes, Identity Center automatically creates the underlying IAM role (`AWSReservedSSO_lablink_<hash>`) in your AWS account. The permission set's status flips to **Provisioned**.

### Step 4 — Sign in

The CLI runs `aws sso login --sso-session lablink`, which opens your browser at the Identity Center sign-in page. Enter your username + password + MFA. AWS caches the access token at `~/.aws/sso/cache/<sha1>.json` and the CLI confirms:

```text
✓ Signed in via Identity Center
✓ AWS Account: 123456789012
✓ Permission set: lablink
✓ Token valid for: 8h 0m
```

You're done — `lablink configure`, `lablink deploy`, etc. now use this session transparently.

## Subsequent logins

Once bootstrap is complete, `lablink login` skips straight to step 4. The browser opens for ~10 seconds while you confirm in the SSO sign-in page, and you're back. SSO access tokens live for 1–12 hours (8 hours by default in Identity Center).

If you run `lablink login` while already signed in:

```text
Already signed in, valid for 4h 12m.
Re-login? [y/N]:
```

Answer `n` if you didn't mean to re-authenticate. Answer `y` to refresh the token early.

## Token expiration mid-command

If your SSO token expires mid-deploy, `lablink ...` commands print:

```text
Your AWS session has expired. Run `lablink login` and try again.
```

Run `lablink login` and re-run the command. There's no silent auto-refresh — keeping the prompt explicit avoids unexpected browser pop-ups during long deploys.

## Updating the policy

When LabLink adds a feature that needs a new AWS service (rare), `lablink doctor` flags the gap:

```text
LabLink permissions   FAIL   Permission set is missing actions: budgets:DescribeBudgets.
                              Run `lablink login --update-policy` to refresh.
```

Run:

```bash
lablink login --update-policy
```

The CLI re-copies the latest policy JSON to your clipboard and opens the AWS console at your `lablink` permission set. Replace the inline policy with the clipboard contents and click **Save**.

## Common issues

### "InvalidRequestException" / "RegisterClient" failure

The `sso_region` in `~/.aws/config` doesn't match where Identity Center lives. Check the IdC dashboard URL (e.g., `https://us-west-2.console.aws.amazon.com/singlesignon/...`) and edit `~/.aws/config`:

```ini
[sso-session lablink]
sso_start_url = https://d-XXXXXXXXXX.awsapps.com/start
sso_region = us-west-2          # ← must match the URL above
sso_registration_scopes = sso:account:access
```

Or wipe and re-bootstrap:

```bash
rm ~/.aws/config
rm -rf ~/.aws/sso/cache
rm -f ~/.lablink/bootstrap-state.json
lablink login
```

### "No valid credential sources found" during `lablink deploy`

Your SSO token has probably expired. Run `lablink login` and retry. If `aws sso login --sso-session lablink` succeeds but the deploy still fails, check that your Terraform version is **≥ 1.6** (older versions don't support SSO with the S3 backend).

### "Permission set is missing actions" in `lablink doctor`

Either the permission set hasn't been assigned to your AWS account yet (status shows "Not provisioned" in IdC), or the inline policy was modified manually. Re-run `lablink login --update-policy` to refresh.

### Bootstrap was interrupted

`lablink login` saves progress to `~/.lablink/bootstrap-state.json` after each step. Re-running picks up where you left off. To start over from scratch:

```bash
rm -f ~/.lablink/bootstrap-state.json
```

Then re-run `lablink login`.

## Resetting login state

To force a fresh first-time bootstrap (e.g., after manually deleting your IdC instance, or to test the flow):

```bash
rm ~/.aws/config                         # remove [sso-session lablink] + [profile lablink]
rm -rf ~/.aws/sso/cache                  # clear cached tokens
rm -f ~/.lablink/bootstrap-state.json    # clear partial bootstrap state
lablink login
```

This **only** resets your local CLI state. Identity Center, your user, the permission set, and assignments persist in AWS — you can paste the same SSO Start URL when bootstrap re-prompts and reuse them.

## Behind the scenes

`lablink login` writes:

| File | Purpose |
|---|---|
| `~/.aws/config` | Adds `[sso-session lablink]` + `[profile lablink]` blocks (preserves any other profiles) |
| `~/.aws/sso/cache/<sha1(lablink)>.json` | The SSO access token — cached and refreshed by `aws sso login` |
| `~/.lablink/bootstrap-state.json` | Bootstrap progress, removed once Step 4 completes |

Subsequent `lablink ...` commands resolve credentials in this order:

1. SSO profile `lablink` from `~/.aws/config` (preferred)
2. `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` environment variables
3. `~/.aws/credentials` default profile
4. Fail with `Run lablink login`

Terraform subprocesses inherit `AWS_PROFILE=lablink` automatically when (1) is in use, so the S3 backend can find your credentials.

## See also

- [First Deployment](first-deployment.md) — runs `lablink login` as Step 0
- [Configuration](../configuration.md) — the `config.yaml` schema
- [AWS Setup (Manual)](../aws-setup.md) — legacy access-key path for users who can't use Identity Center
