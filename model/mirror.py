import hashlib
from datetime import datetime
from inspect import signature

from db.dba import *


class Mirror:

    ENCODING = "cp1252"

    buckets = {}
    buckets_diff = {}
    output = []

    def __init__(self, dba1, dba2, table_name1, table_name2, links):
        """
        Initializes the configuration for checking the data

        Arguments:
            dba1 {DBA} -- Configuration for connection
            to the database of table 1
            dba2 {DBA} -- Configuration for connection
            to the database of table 2
            links {FieldLink[]} -- Array containing the mapping of
            columns from t1 and t2
        """
        self.dba1 = dba1
        self.dba2 = dba2
        self.table_name1 = table_name1
        self.table_name2 = table_name2
        self.links = links

    def run_diff(self):
        print("loading data...")
        self._dataload()
        print("sorting data...")
        self._datasort()
        print("isolating divergences...")
        self._isolate_diffs()
        print("finnished.")
        return self.buckets_diff

    def _where_clause(self, col):
        where = ""
        andd = ""
        clause = ""

        for link in self.links:
            if link.filter:
                colname = link.col1 if col == 1 else link.col2
                filter_val = link.filter1_val if col == 1 else link.filter2_val
                clause = (
                    clause
                    + andd + " "
                    + colname + " = '" + str(filter_val) + "'")
                where = "WHERE"
                andd = "AND"

        return where + clause

    def _queryrun(self, dbconf, table_name, col):
        where = self._where_clause(col)
        sql = """
            SELECT *
            FROM %s %s;
        """ % (table_name, where)

        return dbconf.dict(sql, [])

    def _dataload(self):
        self.data1 = self._queryrun(self.dba1, self.table_name1, 1)
        self.data2 = self._queryrun(self.dba2, self.table_name2, 2)

    def _datasort(self):
        for rec1 in self.data1:
            sha = hashlib.sha256()
            for link in self.links:
                if link.uid:
                    sha.update(self._encodestr(rec1[link.col1]))

            rec1['hash'] = sha.hexdigest()
            self._bucketadd(rec1, 'data1')

        for rec2 in self.data2:
            sha = hashlib.sha256()
            for link in self.links:
                if link.uid:
                    sha.update(self._encodestr(rec2[link.col2]))

            rec2['hash'] = sha.hexdigest()
            self._bucketadd(rec2, 'data2')

    def _isolate_diffs(self):
        for key in self.buckets.keys():
            bucket = self.buckets[key]

            data1 = bucket['data1']
            data1_len = len(data1)
            data2 = bucket['data2']
            data2_len = len(data2)

            # Check for records without match
            if not data1_len == data2_len:
                self.buckets_diff[key] = bucket
                bucket_diff = self.buckets_diff[key]
                message = self._message_notfound()
                bucket_diff['message'] = message
                self._output_add(message, bucket)

            # Check for differences in the data
            for link in self.links:
                if data1_len == 0 or data2_len == 0:
                    break

                # Check if values don't match
                modifiedval1 = link.func1(data1[0][link.col1])
                modifiedval2 = link.func2(data2[0][link.col2])

                if modifiedval1 != modifiedval2:
                    self.buckets_diff[key] = bucket
                    bucket_diff = self.buckets_diff[key]
                    message = self._message_valuenotmatch(link.col1, link.col2)
                    bucket_diff['message'] = message
                    self._output_add(message, bucket, link)

                # Check if values are of the same type
                if isinstance(
                    type(data1[0][link.col1]),
                    type(data2[0][link.col2])
                ):
                    self.buckets_diff[key] = bucket
                    message = self._message_notsametype(link.col1, link.col2)
                    bucket_diff['message'] = message
                    self._output_add(message, bucket, link)

    def _output_add(self, message, bucket, link=None):
        err = {
            'message': message,
            'val1': '',
            'val2': '',
            'links': link,
            'uids1': [],
            'uids2': []
        }

        if link is not None:
            err['val1'] = bucket['data1'][0][link.col1]
            err['val1'] = bucket['data2'][0][link.col2]

        # Look for links that are uids to hel to identify the row with error
        for l in self.links:
            if l.uid:
                if len(bucket['data1']) > 0:
                    err['uids1'].append(bucket['data1'][0][l.col1])
                if len(bucket['data2']) > 0:
                    err['uids2'].append(bucket['data2'][0][l.col2])

        self.output.append(err)

    def _message_notsametype(self, colname1, colname2):
        msg = "Columns '%s' and '%s' values are not of the same type"
        return msg % (colname1, colname2)

    def _message_valuenotmatch(self, colname1, colname2):
        msg = "Colmuns '%s' and '%s' values not match"
        return msg % (colname1, colname2)

    def _message_notfound(self):
        return "Matching record not found"

    def _encodestr(self, val):
        return str(val).encode(self.ENCODING)

    def _bucketadd(self, item, pos):
        if item['hash'] not in self.buckets:
            self.buckets[item['hash']] = self._bucket()

        self.buckets[item['hash']][pos].append(item)

    def _bucket(self):
        return {"message": "", 'data1': [], 'data2': []}

    def to_csv(self):
        dt = datetime.now()
        file = open(
            dt.strftime("%Y-%m-%d %H:%M:%S")
            + "_results.csv", "w+")

        # File header
        file.write("Message,,")
        file.write("val1,val2,")
        for link in self.links:
            if link.uid:
                file.write(link.col1 + ",")
        file.write(",")
        for link in self.links:
            if link.uid:
                file.write(link.col2 + ",")
        file.write("\n")

        for err in self.output:
            file.write(str(err['message']) + ",,")
            file.write(str('"' + err['val1']) + '",')
            file.write(str('"' + err['val2']) + '",')
            for uid in err['uids1']:
                file.write(str(uid) + ",")
            file.write(",")
            for uid in err['uids2']:
                file.write(str(uid) + ",")
            file.write("\n")

        file.close()


class FieldLink:

    def __init__(
        self, col1, col2, func1=None, func2=None, filterr=False,
        filter1_val="", filter2_val="", uid=False
    ):
        self.col1 = col1
        self.col2 = col2
        self.filter = filterr
        self.filter1_val = filter1_val
        self.filter2_val = filter2_val
        self.uid = uid
        self.func1 = self.__validate_func(func1)
        self.func2 = self.__validate_func(func2)

    def __validate_func(self, f):
        if f is None:
            f = self.__default_function
        if not callable(f):
            raise TypeError("func must be a function e.g. foo(bar): pass")
        return f

    def __default_function(self, a):
        """Just a default function to be called in case there is no
        implementation None is passed as argument

        Arguments:
            a {String} -- a string

        Returns:
            String -- a string
        """

        return a
