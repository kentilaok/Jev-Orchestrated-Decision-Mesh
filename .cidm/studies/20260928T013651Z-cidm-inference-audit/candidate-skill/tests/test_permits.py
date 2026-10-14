from pathlib import Path
import copy
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from atomic_mesh import AtomicMesh, MeshError, calculate


class Worker:
    description='Offline fixture'


def choose(phase,options,state): return {'choice':'read','model':'simulation','live':False}


class PermitTests(unittest.TestCase):
    def make(self):
        mesh=AtomicMesh('Read evidence',{'s':{'text':'value 1'}},{'worker':Worker()},choose,simulation=True)
        action={'id':'read','operation':'read_source','objective':'Read s','source_ids':['s'],'arguments':{'source_id':'s'}}
        _,gate=mesh.gate('before_action',{'read':{'worker_id':'worker','action':action},'stop':{}},mesh.context())
        return mesh,action,gate,mesh.permit('worker',action,gate)

    def test_changed_arguments_are_rejected(self):
        mesh,action,gate,permit=self.make(); changed=copy.deepcopy(action); changed['arguments']['source_id']='other'
        with self.assertRaises(MeshError): mesh.dispatch('worker',changed,permit)

    def test_used_receipt_and_gate_are_rejected(self):
        mesh,action,gate,permit=self.make(); mesh.dispatch('worker',action,permit)
        with self.assertRaises(MeshError): mesh.dispatch('worker',action,permit)
        with self.assertRaises(MeshError): mesh.permit('worker',action,gate)

    def test_changed_source_or_issue_invalidates_receipt(self):
        mesh,action,gate,permit=self.make(); mesh.last_issue='new issue'
        with self.assertRaises(MeshError): mesh.dispatch('worker',action,permit)
        mesh,action,gate,permit=self.make(); del mesh.sources['s']
        with self.assertRaises(MeshError): mesh.dispatch('worker',action,permit)

    def test_worker_cannot_mutate_context_alias(self):
        mesh,action,gate,permit=self.make(); mesh.accepted=[{'id':'r1','summary':'original'}]
        context=mesh.context(); context['recent_accepted'][0]['summary']='changed'
        self.assertEqual(mesh.accepted[0]['summary'],'original')

    def test_exact_rational_arithmetic_and_no_code_execution(self):
        self.assertEqual(calculate('0.1+0.2'),calculate('0.3'))
        for text in ('__import__("os")','2**999','x+1','1/0'):
            with self.subTest(text=text),self.assertRaises(MeshError): calculate(text)


if __name__=='__main__': unittest.main()
