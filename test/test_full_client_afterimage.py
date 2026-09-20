"""Compile the exact authored-range policy shipped in the native client patch."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / 'patches/full-client/0024-authored-melee-afterimage.patch'


def added_header():
    lines, active = [], False
    for line in PATCH.read_text().splitlines(True):
        if line.startswith('--- '):
            active = False
        elif line.startswith('+++ '):
            active = line.strip() == '+++ b/src/client/Character/Look/AfterimageRange.h'
        elif active and line.startswith('+'):
            lines.append(line[1:])
    if not lines:
        raise AssertionError('The compiled policy must come from the shipped patch.')
    return ''.join(lines)


HARNESS = r'''
#include "AfterimageRange.h"
#include <cassert>
#include <memory>
#include <vector>

struct Rect {
    int left=0,right=0,top=0,bottom=0;
    int l() const{return left;} int r() const{return right;}
    int t() const{return top;} int b() const{return bottom;}
};
struct Data;
struct Node {
    std::shared_ptr<Data> value;
    Node()=default;
    Node(std::string name, Rect range={}, bool vectors=false);
    std::string name() const;
    std::size_t size() const;
    Node operator[](const std::string&) const;
    Node operator[](int i) const{return (*this)[std::to_string(i)];}
    std::vector<Node>::const_iterator begin() const;
    std::vector<Node>::const_iterator end() const;
    explicit operator bool() const{return bool(value);}
    void add(Node child);
};
struct Data {std::string name;Rect range;bool vectors;std::vector<Node> children;};
Node::Node(std::string n,Rect r,bool v):value(std::make_shared<Data>(Data{n,r,v,{}})){}
const std::vector<Node> empty_nodes;
std::string Node::name()const{return value?value->name:"";}
std::size_t Node::size()const{return value?value->children.size():0;}
Node Node::operator[](const std::string& name)const {
    if(value)for(const auto& child:value->children)if(child.name()==name)return child;
    return {};
}
std::vector<Node>::const_iterator Node::begin()const{return value?value->children.begin():empty_nodes.begin();}
std::vector<Node>::const_iterator Node::end()const{return value?value->children.end():empty_nodes.end();}
void Node::add(Node n){value->children.push_back(n);}
bool valid(Node n){return n&&n.value->vectors&&jrc::valid_melee_range(n.value->range);}
Node bucket(std::string name,Rect range,std::string stance="swingT1",bool vectors=true){
    Node n(name);n.add(Node(stance,range,vectors));return n;
}
Node family(std::initializer_list<Node> children){Node n("swordTL.img");for(Node c:children)n.add(c);return n;}
const Rect authored10{-181,-9,-85,16};
const Rect authored9{-162,-9,-77,16};
bool same(Rect a,Rect b){return a.l()==b.l()&&a.r()==b.r()&&a.t()==b.t()&&a.b()==b.b();}
int main(){
    // Exact valid bucket wins, including when higher/lower children occur first.
    Node f=family({bucket("14",{-220,-5,-100,20}),bucket("9",authored9),bucket("10",authored10)});
    auto exact=jrc::weapon_afterimage(f,10,"swingT1",valid);
    assert(exact&&same(exact.value->range,authored10));
    // The equipped level120 requests bucket12; the authored family ends at10.
    // Nonnumeric and noncanonical names cannot change selection.
    f=family({bucket("charge",{-999,0,-999,999}),bucket("10",authored10),
              bucket("09",{-999,0,-999,999}),bucket("0",{-80,0,-50,5}),bucket("9",authored9)});
    auto missing=jrc::weapon_afterimage(f,12,"swingT1",valid);
    assert(missing&&same(missing.value->range,authored10));
    // Degenerate, inverted, and missing-vector exact paths must fall back.
    for(Node invalid:{bucket("12",{0,0,-20,20}),bucket("12",{-5,-20,-20,20}),
                      bucket("12",{-99,0,-30,20},"swingT1",false)}){
        f=family({invalid,bucket("10",authored10)});
        assert(same(jrc::weapon_afterimage(f,12,"swingT1",valid).value->range,authored10));
    }
    f=family({bucket("12",authored10,"stabO1"),bucket("10",authored9)});
    assert(same(jrc::weapon_afterimage(f,12,"swingT1",valid).value->range,authored9));
    assert(!jrc::weapon_afterimage(f,12,"absent_stance",valid));
    assert(!jrc::weapon_afterimage(family({bucket("14",authored10)}),12,"swingT1",valid));
    assert(!jrc::weapon_afterimage(f,-1,"swingT1",valid));
    Node excessive("swordTL.img");for(int i=0;i<65;i++)excessive.add(bucket(std::to_string(i),authored10));
    assert(!jrc::weapon_afterimage(excessive,12,"swingT1",valid));
    // Unresolved weapon geometry may keep an explicit skill rectangle, but it
    // cannot authorize the generic400px player rectangle as melee reach.
    Rect generic{-400,-5,-50,50}, target=generic;
    const Rect skill{-120,-5,-40,20};
    assert(jrc::authored_melee_range(target,{},skill)&&same(target,skill));
    target=generic;
    assert(!jrc::authored_melee_range(target,{},{}));
    assert(same(target,generic)); // The false result requires caller zero targets.
    assert(jrc::authored_melee_range(target,authored10,skill)&&same(target,authored10));
}
'''


class AuthoredAfterimageTest(unittest.TestCase):
    def test_exact_shipped_policy_with_sparse_authored_buckets(self):
        compiler = shutil.which(os.environ.get('CXX', 'c++'))
        if compiler is None:
            self.skipTest('Native C++ compiler unavailable')
        with tempfile.TemporaryDirectory(prefix='maplebench-afterimage-') as directory:
            root = Path(directory)
            (root / 'AfterimageRange.h').write_text(added_header())
            (root / 'policy.cpp').write_text(HARNESS)
            subprocess.run([compiler, '-std=c++17', '-O0', '-Wall', '-Wextra',
                            '-Werror', str(root/'policy.cpp'), '-o', str(root/'policy')],
                           check=True, capture_output=True, timeout=30)
            subprocess.run([str(root/'policy')], check=True, capture_output=True,
                           timeout=5)

if __name__ == '__main__':
    unittest.main()
