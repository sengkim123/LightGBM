# coding: utf-8
# pylint: skip-file
import os
import tempfile
import unittest

import lightgbm as lgb
import numpy as np
from sklearn.datasets import load_breast_cancer, dump_svmlight_file, load_svmlight_file
from sklearn.model_selection import train_test_split


class TestBasic(unittest.TestCase):

    def test(self):
        X_train, X_test, y_train, y_test = train_test_split(*load_breast_cancer(True),
                                                            test_size=0.1, random_state=2)
        train_data = lgb.Dataset(X_train, label=y_train)
        valid_data = train_data.create_valid(X_test, label=y_test)

        params = {
            "objective": "binary",
            "metric": "auc",
            "min_data": 10,
            "num_leaves": 15,
            "verbose": -1,
            "num_threads": 1,
            "max_bin": 255
        }
        bst = lgb.Booster(params, train_data)
        bst.add_valid(valid_data, "valid_1")

        for i in range(30):
            bst.update()
            if i % 10 == 0:
                print(bst.eval_train(), bst.eval_valid())

        self.assertEqual(bst.current_iteration(), 30)
        self.assertEqual(bst.num_trees(), 30)
        self.assertEqual(bst.num_model_per_iteration(), 1)

        bst.save_model("model.txt")
        pred_from_matr = bst.predict(X_test)
        with tempfile.NamedTemporaryFile() as f:
            tname = f.name
        with open(tname, "w+b") as f:
            dump_svmlight_file(X_test, y_test, f)
        pred_from_file = bst.predict(tname)
        os.remove(tname)
        self.assertEqual(len(pred_from_matr), len(pred_from_file))
        for preds in zip(pred_from_matr, pred_from_file):
            self.assertAlmostEqual(*preds, places=15)

        # check saved model persistence
        bst = lgb.Booster(params, model_file="model.txt")
        pred_from_model_file = bst.predict(X_test)
        self.assertEqual(len(pred_from_matr), len(pred_from_model_file))
        for preds in zip(pred_from_matr, pred_from_model_file):
            # we need to check the consistency of model file here, so test for exact equal
            self.assertEqual(*preds)

        # check early stopping is working. Make it stop very early, so the scores should be very close to zero
        pred_parameter = {"pred_early_stop": True, "pred_early_stop_freq": 5, "pred_early_stop_margin": 1.5}
        pred_early_stopping = bst.predict(X_test, **pred_parameter)
        self.assertEqual(len(pred_from_matr), len(pred_early_stopping))
        for preds in zip(pred_early_stopping, pred_from_matr):
            # scores likely to be different, but prediction should still be the same
            self.assertEqual(preds[0] > 0, preds[1] > 0)

    def test_chunked_dataset(self):
        X_train, X_test, y_train, y_test = train_test_split(*load_breast_cancer(True), test_size=0.1, random_state=2)

        chunk_size = X_train.shape[0] // 10 + 1
        X_train = [X_train[i * chunk_size:(i + 1) * chunk_size, :] for i in range(X_train.shape[0] // chunk_size + 1)]
        X_test = [X_test[i * chunk_size:(i + 1) * chunk_size, :] for i in range(X_test.shape[0] // chunk_size + 1)]

        train_data = lgb.Dataset(X_train, label=y_train, params={"bin_construct_sample_cnt": 100})
        valid_data = train_data.create_valid(X_test, label=y_test, params={"bin_construct_sample_cnt": 100})

        train_data.construct()
        valid_data.construct()

    def test_subset_group(self):
        X_train, y_train = load_svmlight_file(os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                                           '../../examples/lambdarank/rank.train'))
        q_train = np.loadtxt(os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                          '../../examples/lambdarank/rank.train.query'))
        lgb_train = lgb.Dataset(X_train, y_train, group=q_train)
        self.assertEqual(len(lgb_train.get_group()), 201)
        subset = lgb_train.subset(list(lgb.compat.range_(10))).construct()
        subset_group = subset.get_group()
        self.assertEqual(len(subset_group), 2)
        self.assertEqual(subset_group[0], 1)
        self.assertEqual(subset_group[1], 9)

    def test_add_features_throws_if_num_data_unequal(self):
        X1 = np.random.random((1000, 1))
        X2 = np.random.random((100, 1))
        d1 = lgb.Dataset(X1).construct()
        d2 = lgb.Dataset(X2).construct()
        with self.assertRaises(lgb.basic.LightGBMError):
            d1.add_features_from(d2)

    def test_add_features_throws_if_datasets_unconstructed(self):
        X1 = np.random.random((1000, 1))
        X2 = np.random.random((100, 1))
        d1 = lgb.Dataset(X1)
        d2 = lgb.Dataset(X2)
        with self.assertRaises(ValueError):
            d1 = lgb.Dataset(X1)
            d2 = lgb.Dataset(X2)
            d1.add_features_from(d2)
        with self.assertRaises(ValueError):
            d1 = lgb.Dataset(X1).construct()
            d2 = lgb.Dataset(X2)
            d1.add_features_from(d2)
        with self.assertRaises(ValueError):
            d1 = lgb.Dataset(X1)
            d2 = lgb.Dataset(X2).construct()
            d1.add_features_from(d2)

    def test_add_features_equal_data_on_alternating_used_unused(self):
        X = np.random.random((1000, 5))
        X[:, [1, 3]] = 0
        names = ['col_%d' % (i,) for i in range(5)]
        for j in range(1, 5):
            d1 = lgb.Dataset(X[:, :j], feature_name=names[:j]).construct()
            d2 = lgb.Dataset(X[:, j:], feature_name=names[j:]).construct()
            d1.add_features_from(d2)
            with tempfile.NamedTemporaryFile() as f:
                d1name = f.name
            d1.dump_text(d1name)
            d = lgb.Dataset(X, feature_name=names).construct()
            with tempfile.NamedTemporaryFile() as f:
                dname = f.name
            d.dump_text(dname)
            with open(d1name, 'rt') as d1f:
                d1txt = d1f.read()
            with open(dname, 'rt') as df:
                dtxt = df.read()
            os.remove(dname)
            os.remove(d1name)
            self.assertEqual(dtxt, d1txt)

    def test_add_features_same_booster_behaviour(self):
        X = np.random.random((1000, 5))
        X[:, [1, 3]] = 0
        names = ['col_%d' % (i,) for i in range(5)]
        for j in range(1, 5):
            d1 = lgb.Dataset(X[:, :j], feature_name=names[:j]).construct()
            d2 = lgb.Dataset(X[:, j:], feature_name=names[j:]).construct()
            d1.add_features_from(d2)
            d = lgb.Dataset(X, feature_name=names).construct()
            y = np.random.random(1000)
            d1.set_label(y)
            d.set_label(y)
            b1 = lgb.Booster(train_set=d1)
            b = lgb.Booster(train_set=d)
            for k in range(10):
                b.update()
                b1.update()
            with tempfile.NamedTemporaryFile() as df:
                dname = df.name
            with tempfile.NamedTemporaryFile() as d1f:
                d1name = d1f.name
            b1.save_model(d1name)
            b.save_model(dname)
            with open(dname, 'rt') as df:
                dtxt = df.read()
            with open(d1name, 'rt') as d1f:
                d1txt = d1f.read()
            self.assertEqual(dtxt, d1txt)

    def test_get_feature_penalty(self):
        X = np.random.random((1000, 1))
        d = lgb.Dataset(X, params={'feature_penalty': [0.5]}).construct()
        self.assertEqual(np.asarray([0.5]), d.get_feature_penalty())
        d = lgb.Dataset(X).construct()
        self.assertEqual(None, d.get_feature_penalty())

    def test_get_monotone_constraints(self):
        X = np.random.random((1000, 1))
        d = lgb.Dataset(X, params={'monotone_constraints': [1]}).construct()
        self.assertEqual(np.asarray([1]), d.get_monotone_constraints())
        d = lgb.Dataset(X).construct()
        self.assertEqual(None, d.get_monotone_constraints())

    def test_add_features_feature_penalty(self):
        X = np.random.random((1000, 2))
        test_cases = [
            (None, None, None),
            ([0.5], None, [0.5, 1]),
            (None, [0.5], [1, 0.5]),
            ([0.5], [0.5], [0.5, 0.5])]
        for (p1, p2, expected) in test_cases:
            if p1 is not None:
                params1 = {'feature_penalty': p1}
            else:
                params1 = {}
            d1 = lgb.Dataset(X[:, 0].reshape((-1, 1)), params=params1).construct()
            if p2 is not None:
                params2 = {'feature_penalty': p2}
            else:
                params2 = {}
            d2 = lgb.Dataset(X[:, 1].reshape((-1, 1)), params=params2).construct()
            d1.add_features_from(d2)
            actual = d1.get_feature_penalty()
            if isinstance(actual, np.ndarray):
                actual = list(actual)
            self.assertEqual(expected, actual)

    def test_add_features_monotone_types(self):
        X = np.random.random((1000, 2))
        test_cases = [
            (None, None, None),
            ([1], None, [1, 0]),
            (None, [1], [0, 1]),
            ([1], [-1], [1, -1])]
        for (p1, p2, expected) in test_cases:
            if p1 is not None:
                params1 = {'monotone_constraints': p1}
            else:
                params1 = {}
            d1 = lgb.Dataset(X[:, 0].reshape((-1, 1)), params=params1).construct()
            if p2 is not None:
                params2 = {'monotone_constraints': p2}
            else:
                params2 = {}
            d2 = lgb.Dataset(X[:, 1].reshape((-1, 1)), params=params2).construct()
            d1.add_features_from(d2)
            actual = d1.get_monotone_constraints()
            if isinstance(actual, np.ndarray):
                actual = list(actual)
            self.assertEqual(expected, actual)
