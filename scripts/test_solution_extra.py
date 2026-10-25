"""Additional edge checks outside the untouched course tests/ fingerprint."""
import copy
import unittest
from evaluation.solution import score, quality_gate


def fixture():
    rows = [dict(id=str(i), expected='B', choices=['A','B'], slices=[str(i%3)]) for i in range(60)]
    out = [dict(id=r['id'], raw='{"answer":"B"}',error=None) for r in rows]
    r = score(rows,out)
    r.update(model={'kind':'fixture'},status='complete',protocol_sha256='p',golden_sha256='g',baseline_spec_sha256='b',
             behavioral=score(rows[:3],out[:3]))
    return rows,out,r


class Extra(unittest.TestCase):
    def test_duplicate_json_key_is_invalid(self):
        rows,out,_=fixture()
        out[0]['raw']='{"answer":"A","answer":"B"}'
        self.assertEqual(score(rows,out)['overall']['correct'],59)

    def test_error_with_correct_raw_stays_in_denominator(self):
        rows,out,_=fixture()
        out[0]['error']='timeout'
        r=score(rows,out)['overall']
        self.assertEqual((r['n'],r['correct'],r['valid'],r['errors']),(60,59,59,1))

    def test_empty_model_identity_rejected(self):
        _,_,a=fixture()
        b=copy.deepcopy(a);b['model']={'kind':'base'}
        with self.assertRaises(ValueError): quality_gate(a,b,['0'])

    def test_slice_membership_change_rejected(self):
        _,_,a=fixture()
        b=copy.deepcopy(a);b['per_item'][0]['slices']=['1']
        with self.assertRaises(ValueError): quality_gate(a,b,['0'])

    def test_nan_counts_and_fractional_counts_rejected(self):
        _,_,a=fixture()
        for value in (float('nan'),True,60.0):
            b=copy.deepcopy(a);b['overall']['n']=value
            with self.assertRaises(ValueError): quality_gate(a,b,['0'])


if __name__=='__main__': unittest.main(verbosity=2)
