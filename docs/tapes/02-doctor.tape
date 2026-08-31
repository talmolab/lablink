# docs/cli/first-deployment.md — Steps 1-2: inspect the config, then verify.
#
# `show-config` is a pure local read; `doctor` makes read-only AWS calls
# (sts:GetCallerIdentity, s3:HeadBucket). Neither creates anything, so this
# tape is safe to re-run as often as you like.
#
# show-config prints ~65 lines of YAML into a ~40-row terminal, so its output
# scrolls — which is exactly the case that breaks Wait+Screen. See the wait
# rules in _common.tape. The `clear` before doctor is not cosmetic: it also
# puts the doctor table on a fresh screen.

Source "_common.tape"
Output "../assets/videos/cli-02-doctor.mp4"

Hide
Type `export PS1="$ "` Enter
Type "clear" Enter
Show

Sleep 1s
Type "lablink show-config" Sleep 500ms Enter
Wait+Line /^\$$/
Sleep 4s

Type "clear" Sleep 500ms Enter
Sleep 1s
Type "lablink doctor" Sleep 500ms Enter
Wait+Line /^\$$/
Sleep 6s
