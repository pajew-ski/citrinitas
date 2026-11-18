# Security

Citrinitas parses large numbers of files from the open internet. Treat every one as hostile.

## Design

- Fetching and parsing are separate units. The parser has no network and can write only below the data home;
  unpacked sizes are capped on the bytes actually read.
- The API reads and never writes. SQL is limited to a single SELECT on a connection that cannot touch files
  outside the lake, with caps on time, rows and memory. Every request except `/health` needs the token.
- Dependencies are installed with pinned hashes. A commit goes live only after its self-test passed on the
  node.
- The node pulls its code from the branch it was installed from and runs the installer as root inside the
  container. Whoever can push to that branch controls the node: protect the branch.
- The API speaks plain HTTP. Keep the node on a trusted network or put TLS in front of it.

## Reporting

Please report vulnerabilities through GitHub's private vulnerability reporting for this repository, not in a
public issue. Parser crashes on real source files are welcome as normal issues, with the file name and date of
the source file.
