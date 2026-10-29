#!/bin/sh
# Construye el .deb desde code/ y deja el resultado en versions/<version>/,
# con el .deb renombrado para quitar el sufijo "_all" de arquitectura.
set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR/code"

VERSION="$(dpkg-parsechangelog -SVersion)"
dpkg-buildpackage -us -uc -b

cd "$ROOT_DIR"
VERSION_DIR="versions/$VERSION"
mkdir -p "$VERSION_DIR"

for f in ./*_all.deb; do
    [ -e "$f" ] || continue
    mv "$f" "$VERSION_DIR/$(basename "$f" | sed 's/_all\.deb$/.deb/')"
done
mv -f ./*.changes ./*.buildinfo "$VERSION_DIR/" 2>/dev/null || true

echo "Listo: $(ls "$VERSION_DIR"/*.deb)"
