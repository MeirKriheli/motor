# Copyright 2012 10gen, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Test Motor, an asynchronous driver for MongoDB and Tornado."""

import unittest

import pymongo.database
from pymongo.errors import OperationFailure, CollectionInvalid
from pymongo.son_manipulator import AutoReference, NamespaceInjector
from tornado import gen
from tornado.testing import gen_test

import motor
from test import MotorTest, assert_raises


class MotorDatabaseTest(MotorTest):
    @gen_test
    def test_database(self):
        # Test that we can create a db directly, not just from MotorClient's
        # accessors
        db = motor.MotorDatabase(self.cx, 'pymongo_test')

        # Make sure we got the right DB and it can do an operation
        doc = yield db.test_collection.find_one({'_id': 1})
        self.assertEqual(hex(1), doc['s'])

    def test_collection_named_delegate(self):
        db = self.motor_client_sync().pymongo_test
        self.assertTrue(isinstance(db.delegate, pymongo.database.Database))
        self.assertTrue(isinstance(db['delegate'], motor.MotorCollection))
        db.connection.close()

    @gen_test
    def test_database_callbacks(self):
        db = self.cx.pymongo_test
        yield self.check_optional_callback(db.drop_collection, 'c')

        # check_optional_callback would call create_collection twice, and the
        # second call would raise "already exists", so test manually.
        self.assertRaises(TypeError, db.create_collection, 'c', callback='foo')
        self.assertRaises(TypeError, db.create_collection, 'c', callback=1)
        
        # No error without callback
        db.create_collection('c', callback=None)
        
        # Wait for create_collection to complete
        for _ in range(10):
            yield self.pause(0.5)
            if 'c' in (yield db.collection_names()):
                break

        yield self.check_optional_callback(db.validate_collection, 'c')

    @gen_test
    def test_command(self):
        result = yield self.cx.admin.command("buildinfo")
        self.assertEqual(int, type(result['bits']))

    @gen_test
    def test_create_collection(self):
        # Test creating collection, return val is wrapped in MotorCollection,
        # creating it again raises CollectionInvalid.
        db = self.cx.pymongo_test
        yield db.drop_collection('test_collection2')
        collection = yield db.create_collection('test_collection2')
        self.assertTrue(isinstance(collection, motor.MotorCollection))
        self.assertTrue(
            'test_collection2' in (yield db.collection_names()))

        with assert_raises(CollectionInvalid):
            yield db.create_collection('test_collection2')

        yield db.drop_collection('test_collection2')

        # Test creating capped collection
        collection = yield db.create_collection(
            'test_capped', capped=True, size=1000)

        self.assertTrue(isinstance(collection, motor.MotorCollection))
        self.assertEqual(
            {"capped": True, 'size': 1000},
            (yield db.test_capped.options()))
        yield db.drop_collection('test_capped')

    @gen_test
    def test_drop_collection(self):
        # Make sure we can pass a MotorCollection instance to drop_collection
        db = self.cx.pymongo_test
        collection = db.test_drop_collection
        yield collection.insert({})
        names = yield db.collection_names()
        self.assertTrue('test_drop_collection' in names)
        yield db.drop_collection(collection)
        names = yield db.collection_names()
        self.assertFalse('test_drop_collection' in names)

    @gen_test
    def test_command_callback(self):
        yield self.check_optional_callback(
            self.cx.admin.command, 'buildinfo', check=False)

    @gen_test
    def test_auto_ref_and_deref(self):
        # Test same functionality as in PyMongo's test_database.py; the
        # implementation for Motor for async is a little complex so we test
        # that it works here, and we don't just rely on synchrotest
        # to cover it.
        db = self.cx.pymongo_test

        # We test a special hack where add_son_manipulator corrects our mistake
        # if we pass a MotorDatabase, instead of Database, to AutoReference.
        db.add_son_manipulator(AutoReference(db))
        db.add_son_manipulator(NamespaceInjector())

        a = {"hello": u"world"}
        b = {"test": a}
        c = {"another test": b}

        yield db.a.remove({})
        yield db.b.remove({})
        yield db.c.remove({})
        yield db.a.save(a)
        yield db.b.save(b)
        yield db.c.save(c)
        a["hello"] = "mike"
        yield db.a.save(a)
        result_a = yield db.a.find_one()
        result_b = yield db.b.find_one()
        result_c = yield db.c.find_one()

        self.assertEqual(a, result_a)
        self.assertEqual(a, result_b["test"])
        self.assertEqual(a, result_c["another test"]["test"])
        self.assertEqual(b, result_b)
        self.assertEqual(b, result_c["another test"])
        self.assertEqual(c, result_c)

    @gen_test
    def test_authenticate(self):
        db = self.cx.pymongo_test

        yield db.system.users.remove()
        yield db.add_user("mike", "password")
        users = yield db.system.users.find().to_list(length=10)
        self.assertTrue("mike" in [u['user'] for u in users])

        # We need to authenticate many times at once to make sure that
        # Pool's start_request() is properly isolating operations
        for i in range(100):
            db.authenticate(
                "mike", "password", callback=(yield gen.Callback(i)))

        # TODO: remove after copy_authenticate
        outcomes = yield gen.WaitAll(range(100))
        for (result, error), _ in outcomes:
            if error:
                raise error

        # just make sure there are no exceptions here
        yield db.logout()
        yield db.remove_user("mike")
        users = yield db.system.users.find().to_list(length=10)
        self.assertFalse("mike" in [u['user'] for u in users])

    @gen_test
    def test_validate_collection(self):
        db = self.cx.pymongo_test

        with assert_raises(TypeError):
            yield db.validate_collection(5)
        with assert_raises(TypeError):
            yield db.validate_collection(None)
        with assert_raises(OperationFailure):
            yield db.validate_collection("test.doesnotexist")
        with assert_raises(OperationFailure):
            yield db.validate_collection(db.test.doesnotexist)

        yield db.test.save({"dummy": u"object"})
        self.assertTrue((yield db.validate_collection("test")))
        self.assertTrue((yield db.validate_collection(db.test)))


if __name__ == '__main__':
    unittest.main()
