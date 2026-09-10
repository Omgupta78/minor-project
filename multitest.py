"""Checks for multi-photo attendance merging.

Real face detection needs dlib, which is not installed here, so these tests
feed hand-built Face objects into the merge/summary layer. That is exactly the
layer where double-counting bugs would live.
"""
import recognition as rec

failures = []


def check(label, condition, detail=""):
    print(f"{'PASS' if condition else 'FAIL'}  {label}{'  -> ' + detail if detail and not condition else ''}")
    if not condition:
        failures.append(label)


def face(sid, name, distance, image_index, status="matched", left=0):
    return rec.Face(
        top=10, right=left + 50, bottom=60, left=left,
        student_id=sid, name=name, roll_no=f"CS-{sid:03d}",
        distance=distance,
        confidence=rec.distance_to_confidence(distance, rec.MATCH_DISTANCE),
        status=status, image_index=image_index,
    )


# ---- 1. same student in three photos counts once, keeps the best sighting
per_image = [
    [face(1, "Aarav", 0.44, 0), face(2, "Diya", 0.30, 0)],
    [face(1, "Aarav", 0.21, 1)],                      # much better shot
    [face(1, "Aarav", 0.48, 2), face(3, "Kabir", 0.35, 2)],
]
best = rec.merge_across_images(per_image)
check("one entry per student", sorted(best) == [1, 2, 3], str(sorted(best)))
check("best sighting wins", abs(best[1].distance - 0.21) < 1e-9, str(best[1].distance))
check("best sighting keeps its photo", best[1].image_index == 1, str(best[1].image_index))
check("winner stays matched", best[1].status == "matched", best[1].status)

# ---- 2. losing sightings are marked repeat, not duplicate, and keep the name
losers = [f for photo in per_image for f in photo if f.status == "repeat"]
check("two repeats flagged", len(losers) == 2, str(len(losers)))
check("repeats keep the name", all(f.name == "Aarav" for f in losers))
check("no sighting became duplicate",
      not any(f.status == "duplicate" for photo in per_image for f in photo))

# ---- 3. summary counts faces per detection but students once
stats = rec.summarise(per_image, best)
check("photos counted", stats["images_scanned"] == 3, str(stats))
# The /api/scan response carries the per-photo detail array under "images" and
# then merges these counts in. If summarise() ever returns "images" again it
# would replace that array with a number, and the browser would fail with
# "(data.images || []).forEach is not a function".
check("summarise cannot clobber the images array", "images" not in stats, str(stats))
check("faces counted per detection", stats["total_faces"] == 5, str(stats["total_faces"]))
check("students counted once", stats["matched"] == 3, str(stats["matched"]))
check("repeats reported", stats["repeats"] == 2, str(stats["repeats"]))

# ---- 4. more photos never downgrade a student
solo = rec.merge_across_images([[face(1, "Aarav", 0.21, 0)]])
many = rec.merge_across_images([
    [face(1, "Aarav", 0.21, 0)],
    [face(1, "Aarav", 0.59, 1, status="review")],
])
check("extra blurry photo cannot lower confidence",
      many[1].confidence == solo[1].confidence and many[1].status == "matched",
      f"{many[1].status} {many[1].confidence}")

# ---- 5. review-only students stay flagged for the teacher, never auto-present
rev = rec.merge_across_images([[face(9, "Ishaan", 0.57, 0, status="review")]])
check("review stays review", rev[9].status == "review", rev[9].status)
rev_stats = rec.summarise([[face(9, "Ishaan", 0.57, 0, status="review")]], rev)
check("review not counted as matched", rev_stats["matched"] == 0, str(rev_stats))

# ---- 6. unknown faces in any photo are surfaced
unk = [[face(0, "Unknown", 0.9, 0, status="unknown")], [face(4, "Meera", 0.3, 1)]]
unk_best = rec.merge_across_images(unk)
unk_stats = rec.summarise(unk, unk_best)
check("unknown reported", unk_stats["unknown"] >= 1, str(unk_stats))

# ---- 7. empty and single-photo inputs do not blow up
check("no photos is safe", rec.merge_across_images([]) == {})
check("empty photo is safe", rec.summarise([[]], {})["total_faces"] == 0)

print()
if failures:
    print(f"{len(failures)} CHECK(S) FAILED: " + ", ".join(failures))
    raise SystemExit(1)
print("ALL MULTI-PHOTO CHECKS PASSED")
