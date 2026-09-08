# Ranged attack header compatibility

`patches/full-client/0004-ranged-header-padding.patch` adds the four reserved
header bytes expected by Cosmic before target records for these ranged skills:

| Skill ID | Skill |
| --- | --- |
| 3121004 | Bowmaster Hurricane |
| 3221001 | Marksman Piercing Arrow |
| 5221004 | Corsair Rapid Fire |
| 13111002 | Wind Archer Hurricane |

The upstream serializer left this padding as a comment. Its first target ID
therefore began at body offset28 while the server expected offset32. A populated
Hurricane packet was read at the wrong target/damage offsets; an empty one lacked
the complete header. The patch writes zero-valued reserved bytes for exactly
these four skills and only for `Attack::RANGED`. It leaves target records,
damage values, skill IDs, charges, inventory, timing and other packet types alone.

Apply the patch from the Journey checkout root after the existing client patches.
It is independent of the ammunition policy patch and does not modify its files.
A combined client must be rebuilt, frozen and pass ordinary native acceptance
before it can support a class benchmark. The source tests are not that acceptance.

## Source and parser evidence

The preserved fixture `test/fixtures/full-client/AttackAndSkillPackets.h` is the
unmodified upstream header at Journey commit
`bc0234fe7c7f53322453e7bdd79564d9aca4cd8b`, SHA256
`2870c20586e49454a63ff7e70c7e3d084cd77cb6bd2ebe6e7ed6eca979014c4e`.
Its original AGPL-3.0 license notice remains intact.

The server parser was checked against the actual accepted pilot JAR SHA256
`18b9c6febb11d82567ed1a22f53bfc55f00885ebe8eb2d28ab54d6e2df645fca`.
Its `AbstractDealDamageHandler.class` SHA256
`93e24ef28969b0c262ff45d6e989c1bde5120154dad3bbefad8de4a6fa9fd899`
matches the independently inspected compiled class. Its bytecode compares the
four IDs above and invokes `InPacket.skip(4)` before reading targets.
The corresponding `RangedAttackHandler.class` SHA256 is
`8dce43640f6f7994ae48535506de43d866702f75ee5c00d024f6e4fa39abda12`.
This is protocol provenance, not permission to change the server JAR.

## Focused verification

Run `python3 -m unittest discover -s test -p 'test_client_ranged_header.py'`.
The tests apply the actual patch with zero fuzz to the preserved header, compile
the original and patched `AttackPacket` constructors with a small in-memory
packet sink, then read their bytes in the deployed server's header/target order.
They cover the original failure, exact header/first-target/hit alignment for all
four IDs, a complete two-target Hurricane packet, empty special attacks, and
byte-identical ordinary ranged, close and magic controls.

The fixture supplies zero charge and tests header compatibility. Existing
skill-specific charge/trailer behavior is outside this change; these tests do
not claim complete native qualification of Piercing Arrow or Rapid Fire.
No server, model call, network attack or WASM build is invoked by the tests.
