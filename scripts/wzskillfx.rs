//! Offline, deliberately narrow Skill.wz exporter for MapleBench's Hero replay.
//! Uses Maplewright's WZ decoder; no game assets are distributed with the source.
use std::{fs, io::BufWriter};
use wz::img::{decode_canvas, parse_image, WzValue};
use wz::{crypto::WzKey, WzFile};

fn child<'a>(v: &'a WzValue, name: &str) -> Option<&'a WzValue> {
    match v {
        WzValue::Sub(items) => items.iter().find(|(n, _)| n == name).map(|(_, v)| v),
        WzValue::Canvas(c) => c.subs.iter().find(|(n, _)| n == name).map(|(_, v)| v),
        _ => None,
    }
}
fn nav<'a>(root: &'a WzValue, path: &[String]) -> Option<&'a WzValue> {
    let mut node = root;
    for part in path { node = child(node, part)?; }
    Some(node)
}
fn resolve<'a>(root: &'a WzValue, path: &[String]) -> Option<&'a WzValue> {
    let mut path = path.to_vec();
    for _ in 0..16 {
        match nav(root, &path)? {
            WzValue::Uol(link) => {
                path.pop();
                for part in link.split('/') {
                    if part == ".." { path.pop()?; }
                    else if part != "." { path.push(part.to_string()); }
                }
            }
            node => return Some(node),
        }
    }
    None
}
fn int(node: Option<&WzValue>, fallback: i32) -> i32 {
    match node {
        Some(WzValue::Int(v)) => *v,
        Some(WzValue::Short(v)) => *v as i32,
        Some(WzValue::Long(v)) => *v as i32,
        _ => fallback,
    }
}
fn main() {
    let args: Vec<_> = std::env::args().skip(1).collect();
    assert_eq!(args.len(), 2, "usage: wzskillfx <Skill.wz> <outdir>");
    fs::create_dir_all(&args[1]).expect("create effect directory");
    let mut archive = WzFile::open(&args[0]).expect("open Skill.wz");
    let key = WzKey::new(archive.detect_iv(), 0x40000);
    let supported = [
        (1121008, "effect/0"), (1121008, "effect/1"),
        (1111002, "effect"), (1101004, "effect"),
        (1101006, "effect"), (1121002, "effect"), (1121000, "effect"),
    ];
    // Columns preserve raw WZ timing/origin/alpha rather than resampling the art.
    let mut manifest = String::from("# maplebench-skill-fx-v1 Skill.wz\n# skill path frame delay file originX originY alpha0 alpha1 blend source\n");
    let mut total = 0;
    for (skill, effect) in supported {
        let image_name = format!("{}.img", skill / 10000);
        let (_, offset) = archive.find_image_path(&[&image_name], &key).expect("find skill image");
        let image = parse_image(&mut archive.reader, offset, &key);
        let base: Vec<String> = format!("skill/{skill}/{effect}").split('/').map(String::from).collect();
        let sequence = resolve(&image, &base).expect("find supported skill effect");
        let additive = int(child(sequence, "blend"), 0);
        assert!((0..=1).contains(&additive), "unsupported blend mode");
        let mut count = 0;
        for frame in 0..128 {
            let mut path = base.clone();
            path.push(frame.to_string());
            let Some(node) = resolve(&image, &path) else { break };
            let WzValue::Canvas(canvas) = node else { panic!("non-canvas skill effect frame") };
            let (width, height, rgba) = decode_canvas(archive.reader.all(), canvas, &key).expect("decode skill effect");
            assert!(width > 0 && height > 0);
            let (ox, oy) = match child(node, "origin") {
                Some(WzValue::Vector(x, y)) => (*x, *y),
                _ => panic!("effect frame missing WZ origin"),
            };
            let delay = int(child(node, "delay"), 100).max(1);
            let a0 = int(child(node, "a0"), 255).clamp(0, 255);
            let a1 = int(child(node, "a1"), a0).clamp(0, 255);
            let file = format!("{skill}_{}_{frame}.png", effect.replace('/', "_"));
            let output = fs::File::create(format!("{}/{file}", args[1])).expect("create effect PNG");
            let mut encoder = png::Encoder::new(BufWriter::new(output), width, height);
            encoder.set_color(png::ColorType::Rgba);
            encoder.set_depth(png::BitDepth::Eight);
            encoder.write_header().unwrap().write_image_data(&rgba).unwrap();
            manifest += &format!("{skill} {effect} {frame} {delay} {file} {ox} {oy} {a0} {a1} {additive} {image_name}/{}/{frame}\n", base.join("/"));
            count += 1;
        }
        assert!(count > 0, "supported skill has no frames");
        total += count;
        println!("skill {skill}/{effect}: {count} original WZ frames");
    }
    fs::write(format!("{}/effects.txt", args[1]), manifest).expect("write effect manifest");
    println!("exported {total} original Skill.wz frames");
}
