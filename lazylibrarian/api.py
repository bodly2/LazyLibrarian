#  This file is part of Lazylibrarian.
#
#  Lazylibrarian is free software':'you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Lazylibrarian is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Lazylibrarian.  If not, see <http://www.gnu.org/licenses/>.

from lazylibrarian import importer, logger, database
from lazylibrarian.searchnzb import search_nzb_book
from lazylibrarian.searchtorrents import search_tor_book
from lazylibrarian.searchmag import search_magazines
from lazylibrarian.searchrss import search_rss_book
from lazylibrarian.gr import GoodReads
from lazylibrarian.gb import GoogleBooks
from lazylibrarian.common import clearLog, cleanCache, restartJobs, showJobs, checkRunningJobs
from lazylibrarian.formatter import today
from lazylibrarian.updater import dbUpdate
from lazylibrarian.magazinescan import magazineScan
from lazylibrarian.csv import import_CSV, export_CSV
from lazylibrarian.postprocess import processDir, processAlternate
from lazylibrarian.librarysync import LibraryScan
from lazylibrarian.bookwork import setWorkPages, getBookCovers, getWorkSeries, getWorkPage, getBookCover, getAuthorImage, getAuthorImages

import lazylibrarian
import json
import threading
import Queue

cmd_dict = {'help': 'list available commands. ' +
            'Time consuming commands take an optional &wait parameter if you want to wait for completion, ' +
            'otherwise they return OK straight away and run in the background',
            'getIndex': 'list all authors',
            'getAuthor': '&id= get author and list their books from AuthorID',
            'getAuthorImage': '&name= get image for this author',
            'getAuthorImages': '[&wait] get images for all authors without one',
            'getWanted': 'list wanted books',
            'getSnatched': 'list snatched books',
            'getHistory': 'list history',
            'getLogs': 'show current log',
            'clearLogs': 'clear current log',
            'getMagazines': 'list magazines',
            'getIssues': '&name= list issues for named magazine',
            'forceMagSearch': '[&wait] search for all wanted magazines',
            'forceBookSearch': '[&wait] search for all wanted books',
            'forceProcess': 'process books/mags in download dir',
            'pauseAuthor': '&id= pause author by AuthorID',
            'resumeAuthor': '&id= resume author by AuthorID',
            'ignoreAuthor': '&id= ignore author by AuthorID',
            'unignoreAuthor': '&id= unignore author by AuthorID',
            'refreshAuthor': '&name= refresh author by name',
            'forceActiveAuthorsUpdate': '[&wait] refresh all active authors and reload their books',
            'forceLibraryScan': '[&wait] refresh whole book library',
            'forceMagazineScan': '[&wait] refresh whole magazine library',
            'getVersion': 'show git version',
            'shutdown': 'stop lazylibrarian',
            'restart': 'restart lazylibrarian',
            'update': 'update lazylibrarian',
            'findAuthor': '&name= search goodreads/googlebooks for named author',
            'findBook': '&name= search goodreads/googlebooks for named book',
            'moveBooks': '&fromname= &toname= move all books from one author to another by AuthorName',
            'moveBook': '&id= &toid= move one book to new author by BookID and AuthorID',
            'addAuthor': '&name= add author to database by name',
            'removeAuthor': '&id= removee author from database by AuthorID',
            'addMagazine': '&name= add magazine to database by name',
            'removeMagazine': '&name= remove magazine and issues from database by name',
            'queueBook': '&id= mark book as Wanted',
            'unqueueBook': '&id= mark book as Skipped',
            'readCFG': '&name=&group= read value of config variable "name" in section "group"',
            'writeCFG': '&name=&group=&value= set config variable "name" in section "group" to value',
            'loadCFG': 'reload config from file',
            'getBookCover': '&id= fetch a link to a cover from cache/librarything/goodreads/google for a BookID',
            'getAllBooks': 'list all books in the database',
            'searchBook': '&id= [&wait] search for one book by BookID',
            'showJobs': 'show status of running jobs',
            'restartJobs': 'reschedule/restart background jobs',
            'checkRunningJobs': 'ensure all needed jobs are running',
            'getWorkSeries': '&id= Get series & seriesNum from Librarything BookWork using BookID',
            'getWorkPage': '&id= Get url of Librarything BookWork using BookID',
            'getBookCovers': '[&wait] Check all books for cached cover and download if missing',
            'cleanCache': '[&wait] Clean unused/old files from the LazyLibrarian caches',
            'setWorkPages': '[&wait] Set the WorkPages links in the database',
            'importAlternate': '[&wait] [&dir=] Import books from named or alternate folder and any subfolders',
            'importCSVwishlist': '[&wait] [&dir=] Import a CSV wishlist from named or alternate directory',
            'exportCSVwishlist': '[&wait] [&dir=] Export a CSV wishlist to named or alternate directory'
            }


class Api(object):

    def __init__(self):

        self.apikey = None
        self.cmd = None
        self.id = None

        self.kwargs = None

        self.data = None

        self.callback = None

    def checkParams(self, *args, **kwargs):

        if not lazylibrarian.API_ENABLED:
            self.data = 'API not enabled'
            return
        if not lazylibrarian.API_KEY:
            self.data = 'API key not generated'
            return
        if len(lazylibrarian.API_KEY) != 32:
            self.data = 'API key not generated correctly'
            return

        if 'apikey' not in kwargs:
            self.data = 'Missing api key'
            return

        if kwargs['apikey'] != lazylibrarian.API_KEY:
            self.data = 'Incorrect API key'
            return
        else:
            self.apikey = kwargs.pop('apikey')

        if 'cmd' not in kwargs:
            self.data = 'Missing parameter: cmd, try cmd=help'
            return

        if kwargs['cmd'] not in cmd_dict:
            self.data = 'Unknown command: %s, try cmd=help' % kwargs['cmd']
            return
        else:
            self.cmd = kwargs.pop('cmd')

        self.kwargs = kwargs
        self.data = 'OK'

    def fetchData(self):

        threadname = threading.currentThread().name
        if "Thread-" in threadname:
            threading.currentThread().name = "API"

        if self.data == 'OK':
            args = []
            if 'name' in self.kwargs:
                args.append({"name": self.kwargs['name']})
            if 'id' in self.kwargs:
                args.append({"id": self.kwargs['id']})
            if 'group' in self.kwargs:
                args.append({"group": self.kwargs['group']})
            if 'value' in self.kwargs:
                args.append({"value": self.kwargs['value']})
            if 'wait' in self.kwargs:
                args.append({"wait": "True"})
            if args == []:
                args = ''
            logger.info('Received API command: %s %s' % (self.cmd, args))
            methodToCall = getattr(self, "_" + self.cmd)
            methodToCall(**self.kwargs)
            if 'callback' not in self.kwargs:
                if isinstance(self.data, basestring):
                    return self.data
                else:
                    return json.dumps(self.data)
            else:
                self.callback = self.kwargs['callback']
                self.data = json.dumps(self.data)
                self.data = self.callback + '(' + self.data + ');'
                return self.data
        else:
            return self.data

    def _dic_from_query(self, query):

        myDB = database.DBConnection()
        rows = myDB.select(query)

        rows_as_dic = []

        for row in rows:
            row_as_dic = dict(zip(row.keys(), row))
            rows_as_dic.append(row_as_dic)

        return rows_as_dic

    def _help(self, **kwargs):
        self.data = dict(cmd_dict)

    def _getHistory(self, **kwargs):
        self.data = self._dic_from_query(
            "SELECT * from wanted WHERE Status != 'Skipped' and Status != 'Ignored'")

    def _getWanted(self, **kwargs):
        self.data = self._dic_from_query(
            "SELECT * from books WHERE Status='Wanted'")

    def _getSnatched(self, **kwargs):
        self.data = self._dic_from_query(
            "SELECT * from books WHERE Status='Snatched'")

    def _getLogs(self, **kwargs):
        self.data = lazylibrarian.LOGLIST

    def _clearLogs(self, **kwargs):
        self.data = clearLog()

    def _getIndex(self, **kwargs):
        self.data = self._dic_from_query(
            'SELECT * from authors order by AuthorName COLLATE NOCASE')

    def _getAuthor(self, **kwargs):
        if 'id' not in kwargs:
            self.data = 'Missing parameter: id'
            return
        else:
            self.id = kwargs['id']

        author = self._dic_from_query(
            'SELECT * from authors WHERE AuthorID="' + self.id + '"')
        books = self._dic_from_query(
            'SELECT * from books WHERE AuthorID="' + self.id + '"')

        self.data = {'author': author, 'books': books}

    def _getMagazines(self, **kwargs):
        self.data = self._dic_from_query('SELECT * from magazines order by Title COLLATE NOCASE')

    def _getAllBooks(self, **kwargs):
        self.data = self._dic_from_query(
            'SELECT AuthorID,AuthorName,AuthorLink, BookName,BookSub,BookGenre,BookIsbn,BookPub, \
            BookRate,BookImg,BookPages,BookLink,BookID,BookDate, BookLang,BookAdded,Status,Series,SeriesNum \
            from books')

    def _getIssues(self, **kwargs):
        if 'name' not in kwargs:
            self.data = 'Missing parameter: name'
            return
        else:
            self.id = kwargs['name']

        magazine = self._dic_from_query(
            'SELECT * from magazines WHERE Title="' + self.id + '"')
        issues = self._dic_from_query(
            'SELECT * from issues WHERE Title="' + self.id + '" order by IssueDate DESC')

        self.data = {
            'magazine': magazine, 'issues': issues}

    def _getBook(self, **kwargs):
        if 'id' not in kwargs:
            self.data = 'Missing parameter: id'
            return
        else:
            self.id = kwargs['id']

        book = self._dic_from_query(
            'SELECT * from books WHERE BookID="' + self.id + '"')
        self.data = {'book': book}

    def _queueBook(self, **kwargs):
        if 'id' not in kwargs:
            self.data = 'Missing parameter: id'
            return
        else:
            self.id = kwargs['id']

        myDB = database.DBConnection()
        controlValueDict = {'BookID': self.id}
        newValueDict = {'Status': 'Wanted'}
        myDB.upsert("books", newValueDict, controlValueDict)

    def _unqueueBook(self, **kwargs):
        if 'id' not in kwargs:
            self.data = 'Missing parameter: id'
            return
        else:
            self.id = kwargs['id']

        myDB = database.DBConnection()
        controlValueDict = {'BookID': self.id}
        newValueDict = {'Status': 'Skipped'}
        myDB.upsert("books", newValueDict, controlValueDict)

    def _addMagazine(self, **kwargs):
        if 'name' not in kwargs:
            self.data = 'Missing parameter: name'
            return
        else:
            self.id = kwargs['name']

        controlValueDict = {"Title": self.id}
        newValueDict = {
            "Frequency": None,
            "Regex": None,
            "Status": "Active",
            "MagazineAdded": today(),
            "IssueStatus": "Wanted"
        }
        myDB.upsert("magazines", newValueDict, controlValueDict)

    def _removeMagazine(self, **kwargs):
        if 'name' not in kwargs:
            self.data = 'Missing parameter: name'
            return
        else:
            self.id = kwargs['name']

        myDB = database.DBConnection()
        myDB.action('DELETE from magazines WHERE Title="%s"' % self.id)
        myDB.action('DELETE from wanted WHERE BookID="%s"' % self.id)
        myDB.action('DELETE from issues WHERE Title="%s"' % self.id)

    def _pauseAuthor(self, **kwargs):
        if 'id' not in kwargs:
            self.data = 'Missing parameter: id'
            return
        else:
            self.id = kwargs['id']

        myDB = database.DBConnection()
        controlValueDict = {'AuthorID': self.id}
        newValueDict = {'Status': 'Paused'}
        myDB.upsert("authors", newValueDict, controlValueDict)

    def _ignoreAuthor(self, **kwargs):
        if 'id' not in kwargs:
            self.data = 'Missing parameter: id'
            return
        else:
            self.id = kwargs['id']

        myDB = database.DBConnection()
        controlValueDict = {'AuthorID': self.id}
        newValueDict = {'Status': 'Ignored'}
        myDB.upsert("authors", newValueDict, controlValueDict)

    def _unignoreAuthor(self, **kwargs):
        if 'id' not in kwargs:
            self.data = 'Missing parameter: id'
            return
        else:
            self.id = kwargs['id']

        myDB = database.DBConnection()
        controlValueDict = {'AuthorID': self.id}
        newValueDict = {'Status': 'Active'}
        myDB.upsert("authors", newValueDict, controlValueDict)

    def _resumeAuthor(self, **kwargs):
        if 'id' not in kwargs:
            self.data = 'Missing parameter: id'
            return
        else:
            self.id = kwargs['id']

        myDB = database.DBConnection()
        controlValueDict = {'AuthorID': self.id}
        newValueDict = {'Status': 'Active'}
        myDB.upsert("authors", newValueDict, controlValueDict)

    def _refreshAuthor(self, **kwargs):
        if 'name' not in kwargs:
            self.data = 'Missing parameter: name'
            return
        else:
            self.id = kwargs['name']

        try:
            importer.addAuthorToDB(self.id, refresh=True)
        except Exception as e:
            self.data = str(e)

    def _forceActiveAuthorsUpdate(self, **kwargs):
        if 'wait' in kwargs:
            dbUpdate(False)
        else:
            threading.Thread(target=dbUpdate, name='API-DBUPDATE', args=[False]).start()

    def _forceMagSearch(self, **kwargs):
        if lazylibrarian.USE_NZB() or lazylibrarian.USE_TOR():
            if 'wait' in kwargs:
                search_magazines(None, True)
            else:
                threading.Thread(target=search_magazines, name='API-SEARCHMAGS', args=[None, True]).start()
        else:
            self.data = 'No search methods set, check config'

    def _forceBookSearch(self, **kwargs):
        if lazylibrarian.USE_NZB():
            if 'wait' in kwargs:
                search_nzb_book()
            else:
                threading.Thread(target=search_nzb_book, name='API-SEARCHNZB', args=[]).start()
        if lazylibrarian.USE_TOR():
            if 'wait' in kwargs:
                search_tor_book()
            else:
                threading.Thread(target=search_tor_book, name='API-SEARCHTOR', args=[]).start()
        if lazylibrarian.USE_RSS():
            if 'wait' in kwargs:
                search_rss_book()
            else:
                threading.Thread(target=search_rss_book, name='API-SEARCHRSS', args=[]).start()
        if not lazylibrarian.USE_RSS() and not lazylibrarian.USE_NZB() and not lazylibrarian.USE_TOR():
            self.data = "No search methods set, check config"

    def _forceProcess(self, **kwargs):
        processDir()

    def _forceLibraryScan(self, **kwargs):
        if 'wait' in kwargs:
            LibraryScan()
        else:
            threading.Thread(target=LibraryScan, name='API-LIBRARYSCAN', args=[]).start()

    def _forceMagazineScan(self, **kwargs):
        if 'wait' in kwargs:
            magazineScan()
        else:
            threading.Thread(target=magazineScan, name='API-MAGSCAN', args=[]).start()

    def _cleanCache(self, **kwargs):
        if 'wait' in kwargs:
            cleanCache()
        else:
            threading.Thread(target=cleanCache, name='API-CLEANCACHE', args=[]).start()

    def _setWorkPages(self, **kwargs):
        if 'wait' in kwargs:
            setWorkPages()
        else:
            threading.Thread(target=setWorkPages, name='API-SETWORKPAGES', args=[]).start()

    def _getBookCovers(self, **kwargs):
        if 'wait' in kwargs:
            getBookCovers()
        else:
            threading.Thread(target=getBookCovers, name='API-GETBOOKCOVERS', args=[]).start()

    def _getAuthorImages(self, **kwargs):
        if 'wait' in kwargs:
            getAuthorImages()
        else:
            threading.Thread(target=getAuthorImages, name='API-GETAUTHORIMAGES', args=[]).start()

    def _getVersion(self, **kwargs):
        self.data = {
            'install_type': lazylibrarian.INSTALL_TYPE,
            'current_version': lazylibrarian.CURRENT_VERSION,
            'latest_version': lazylibrarian.LATEST_VERSION,
            'commits_behind': lazylibrarian.COMMITS_BEHIND,
        }

    def _shutdown(self, **kwargs):
        lazylibrarian.SIGNAL = 'shutdown'

    def _restart(self, **kwargs):
        lazylibrarian.SIGNAL = 'restart'

    def _update(self, **kwargs):
        lazylibrarian.SIGNAL = 'update'

    def _findAuthor(self, **kwargs):
        if 'name' not in kwargs:
            self.data = 'Missing parameter: name'
            return

        myDB = database.DBConnection()
        if lazylibrarian.BOOK_API == "GoogleBooks":
            GB = GoogleBooks(kwargs['name'])
            queue = Queue.Queue()
            search_api = threading.Thread(target=GB.find_results, name='API-GBRESULTS', args=[kwargs['name'], queue])
            search_api.start()
        elif lazylibrarian.BOOK_API == "GoodReads":
            queue = Queue.Queue()
            GR = GoodReads(kwargs['name'])
            search_api = threading.Thread(target=GR.find_results, name='API-GRRESULTS', args=[kwargs['name'], queue])
            search_api.start()

        search_api.join()
        self.data = queue.get()

    def _findBook(self, **kwargs):
        if 'name' not in kwargs:
            self.data = 'Missing parameter: name'
            return
        myDB = database.DBConnection()
        if lazylibrarian.BOOK_API == "GoogleBooks":
            GB = GoogleBooks(kwargs['name'])
            queue = Queue.Queue()
            search_api = threading.Thread(target=GB.find_results, name='API-GBRESULTS', args=[kwargs['name'], queue])
            search_api.start()
        elif lazylibrarian.BOOK_API == "GoodReads":
            queue = Queue.Queue()
            GR = GoodReads(kwargs['name'])
            search_api = threading.Thread(target=GR.find_results, name='API-GRRESULTS', args=[kwargs['name'], queue])
            search_api.start()

        search_api.join()
        self.data = queue.get()

    def _moveBook(self, **kwargs):
        if 'id' not in kwargs:
            self.data = 'Missing parameter: id'
            return
        if 'toid' not in kwargs:
            self.data = 'Missing parameter: toid'
            return
        try:
            myDB = database.DBConnection()
            authordata = myDB.match(
                'SELECT AuthorName, AuthorLink from authors WHERE AuthorID="%s"' % kwargs['toid'])
            if not authordata:
                self.data = "No destination author [%s] in the database" % kwargs['toid']
            else:
                bookdata = myDB.match(
                    'SELECT AuthorID, BookName from books where BookID="%s"' %
                    kwargs['id'])
                if not bookdata:
                    self.data = "No bookid [%s] in the database" % kwargs['id']
                else:
                    controlValueDict = {'BookID': kwargs['id']}
                    newValueDict = {
                        'AuthorID': kwargs['toid'],
                        'AuthorName': authordata[0],
                        'AuthorLink': authordata[1]
                    }
                    myDB.upsert("books", newValueDict, controlValueDict)
                    importer.update_totals(bookdata[0])    # we moved from here
                    importer.update_totals(kwargs['toid'])  # to here
                    self.data = "Moved book [%s] to [%s]" % (bookdata[1], authordata[0])
            logger.debug(self.data)
        except Exception as e:
            self.data = str(e)

    def _moveBooks(self, **kwargs):
        if 'fromname' not in kwargs:
            self.data = 'Missing parameter: fromname'
            return
        if 'toname' not in kwargs:
            self.data = 'Missing parameter: toname'
            return
        try:
            myDB = database.DBConnection()

            fromhere = myDB.select(
                'SELECT bookid,authorid from books where authorname="%s"' % kwargs['fromname'])
            tohere = myDB.match(
                'SELECT authorid, authorlink from authors where authorname="%s"' % kwargs['toname'])
            if not len(fromhere):
                self.data = "No books by [%s] in the database" % kwargs['fromname']
            else:
                if not tohere:
                    self.data = "No destination author [%s] in the database" % kwargs['toname']
                else:
                    myDB.action(
                        'UPDATE books SET authorid="%s", authorname="%s", authorlink="%s" where authorname="%s"' %
                        (tohere[0], kwargs['toname'], tohere[1], kwargs['fromname']))
                    self.data = "Moved %s books from %s to %s" % (len(fromhere), kwargs['fromname'], kwargs['toname'])
                    importer.update_totals(fromhere[0][1])    # we moved from here
                    importer.update_totals(tohere[0])  # to here

            logger.debug(self.data)
        except Exception as e:
            self.data = str(e)

    def _addAuthor(self, **kwargs):
        if 'name' not in kwargs:
            self.data = 'Missing parameter: name'
            return
        else:
            self.id = kwargs['name']
        try:
            importer.addAuthorToDB(self.id, refresh=False)
        except Exception as e:
            self.data = str(e)

    def _searchBook(self, **kwargs):
        if 'id' not in kwargs:
            self.data = 'Missing parameter: id'
            return
        else:
            self.id = kwargs['id']

        books = [{"bookid": id}]
        if lazylibrarian.USE_RSS():
            if 'wait' in kwargs:
                search_rss_book(books)
            else:
                threading.Thread(target=search_rss_book, name='API-SEARCHRSS', args=[books]).start()
        if lazylibrarian.USE_NZB():
            if 'wait' in kwargs:
                search_nzb_book(books)
            else:
                threading.Thread(target=search_nzb_book, name='API-SEARCHNZB', args=[books]).start()
        if lazylibrarian.USE_TOR():
            if 'wait' in kwargs:
                search_tor_book(books)
            else:
                threading.Thread(target=search_tor_book, name='API-SEARCHTOR', args=[books]).start()
        if not lazylibrarian.USE_RSS() and not lazylibrarian.USE_NZB() and not lazylibrarian.USE_TOR():
            self.data = "No search methods set, check config"

    def _removeAuthor(self, **kwargs):
        if 'id' not in kwargs:
            self.data = 'Missing parameter: id'
            return
        else:
            self.id = kwargs['id']

        myDB = database.DBConnection()
        authorsearch = myDB.select(
            'SELECT AuthorName from authors WHERE AuthorID="%s"' % AuthorID)
        if len(authorsearch):  # to stop error if try to remove an author while they are still loading
            AuthorName = authorsearch[0]['AuthorName']
            logger.info(u"Removing all references to author: %s" % AuthorName)
            myDB.action('DELETE from authors WHERE AuthorID="%s"' % AuthorID)
            myDB.action('DELETE from books WHERE AuthorID="%s"' % AuthorID)

    def _writeCFG(self, **kwargs):
        if 'name' not in kwargs:
            self.data = 'Missing parameter: name'
            return
        if 'value' not in kwargs:
            self.data = 'Missing parameter: value'
            return
        if 'group' not in kwargs:
            self.data = 'Missing parameter: group'
            return
        try:
            self.data = '["%s"]' % lazylibrarian.CFG.get(kwargs['group'], kwargs['name'])
            lazylibrarian.CFG.set(kwargs['group'], kwargs['name'], kwargs['value'])
            with open(lazylibrarian.CONFIGFILE, 'wb') as configfile:
                lazylibrarian.CFG.write(configfile)
            lazylibrarian.config_read(reloaded=True)
        except Exception as e:
            self.data = 'Unable to update CFG entry for %s: %s, %s' % (kwargs['group'], kwargs['name'], str(e))

    def _readCFG(self, **kwargs):
        if 'name' not in kwargs:
            self.data = 'Missing parameter: name'
            return
        if 'group' not in kwargs:
            self.data = 'Missing parameter: group'
            return
        try:
            self.data = '["%s"]' % lazylibrarian.CFG.get(kwargs['group'], kwargs['name'])
        except Exception:
            self.data = 'No CFG entry for %s: %s' % (kwargs['group'], kwargs['name'])

    def _loadCFG(self, **kwargs):
        lazylibrarian.config_read(reloaded=True)

    def _getWorkSeries(self, **kwargs):
        if 'id' not in kwargs:
            self.data = 'Missing parameter: id'
            return
        else:
            self.id = kwargs['id']
        self.data = getWorkSeries(self.id)

    def _getWorkPage(self, **kwargs):
        if 'id' not in kwargs:
            self.data = 'Missing parameter: id'
            return
        else:
            self.id = kwargs['id']
        self.data = getWorkPage(self.id)

    def _getBookCover(self, **kwargs):
        if 'id' not in kwargs:
            self.data = 'Missing parameter: id'
            return
        else:
            self.id = kwargs['id']
        self.data = getBookCover(self.id)

    def _getAuthorImage(self, **kwargs):
        if 'name' not in kwargs:
            self.data = 'Missing parameter: name'
            return
        else:
            self.id = kwargs['name']
        self.data = getAuthorImage(self.name)

    def _restartJobs(self, **kwargs):
        restartJobs(start='Restart')

    def _checkRunningJobs(self, **kwargs):
        checkRunningJobs()

    def _showJobs(self, **kwargs):
        self.data = showJobs()

    def _importAlternate(self, **kwargs):
        if 'dir' in kwargs:
            usedir = kwargs['dir']
        else:
            usedir = lazylibrarian.ALTERNATE_DIR
        if 'wait' in kwargs:
            processAlternate(usedir)
        else:
            threading.Thread(target=processAlternate, name='API-IMPORTALT', args=[usedir]).start()

    def _importCSVwishlist(self, **kwargs):
        if 'dir' in kwargs:
            usedir = kwargs['dir']
        else:
            usedir = lazylibrarian.ALTERNATE_DIR
        if 'wait' in kwargs:
            import_CSV(usedir)
        else:
            threading.Thread(target=import_CSV, name='API-IMPORTCSV', args=[usedir]).start()

    def _exportCSVwishlist(self, **kwargs):
        if 'dir' in kwargs:
            usedir = kwargs['dir']
        else:
            usedir = lazylibrarian.ALTERNATE_DIR
        if 'wait' in kwargs:
            export_CSV(usedir)
        else:
            threading.Thread(target=export_CSV, name='API-EXPORTCSV', args=[usedir]).start()
